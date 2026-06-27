import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  ApiError,
  acceptInvite,
  addNote,
  authenticatedRequest,
  castVotes,
  createInvite,
  createLeague,
  getAccessToken,
  getInvitePreview,
  getLeague,
  getLeagueMembers,
  getLeagues,
  getMe,
  getMyVotes,
  getNotes,
  getResults,
  logout,
  logoutAll,
  refresh,
  removeMember,
  requestMagicLink,
  setStoredAccessToken,
  updateDisplayName,
  updateLeague,
  verifyToken,
} from "./api";
import type {
  Invite,
  InvitePreview,
  League,
  LeagueMember,
  Note,
  RoundResults,
  UserProfile,
  Votes,
} from "./api";

const API_BASE = "http://127.0.0.1:8000";
const AUTH_BASE = `${API_BASE}/api/v1/auth`;
const V1_BASE = `${API_BASE}/api/v1`;

/** A representative League object as the backend would return it. */
const sampleLeague: League = {
  id: "league-1",
  name: "Friday Mixers",
  description: "weekly picks",
  organizer_id: "user-1",
  total_rounds: 6,
  votes_per_player: 3,
  songs_per_submission: 1,
  current_round: 0,
  state: "active",
  default_vibe_mode: false,
  created_at: "2026-06-01T00:00:00Z",
  completed_at: null,
};

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
    it("POSTs the email to /auth/request and resolves with a null devToken on 200", async () => {
      const fetchMock = vi
        .spyOn(globalThis, "fetch")
        .mockResolvedValue(jsonResponse(200, { message: "ok" }));

      await expect(requestMagicLink("user@example.com")).resolves.toEqual({
        devToken: null,
      });

      expect(fetchMock).toHaveBeenCalledTimes(1);
      const [url, init] = fetchMock.mock.calls[0];
      expect(url).toBe(`${AUTH_BASE}/request`);
      expect(init?.method).toBe("POST");
      expect(init?.body).toBe(JSON.stringify({ email: "user@example.com" }));
      expect((init?.headers as Record<string, string>)["Content-Type"]).toBe("application/json");
    });

    it("returns the dev_token from the body when present (dev/staging)", async () => {
      vi.spyOn(globalThis, "fetch").mockResolvedValue(
        jsonResponse(200, { message: "ok", dev_token: "tok-xyz" }),
      );

      await expect(requestMagicLink("user@example.com")).resolves.toEqual({
        devToken: "tok-xyz",
      });
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
      vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response("nope", { status: 500 }));

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
      // URLSearchParams form-encodes the token (space → "+"); no invite param
      // when none is passed.
      const params = new URLSearchParams({ token: "a b/c?d" });
      expect(url).toBe(`${AUTH_BASE}/verify?${params.toString()}`);
      expect(String(url)).not.toContain("invite=");
      expect(init?.method).toBe("GET");
      expect(init?.credentials).toBe("include");
    });

    it("appends the invite token when one is provided", async () => {
      const fetchMock = vi
        .spyOn(globalThis, "fetch")
        .mockResolvedValue(jsonResponse(200, { access_token: "tok", token_type: "bearer" }));

      await verifyToken("magic", "inv-123");

      const [url] = fetchMock.mock.calls[0];
      expect(String(url)).toContain("token=magic");
      expect(String(url)).toContain("invite=inv-123");
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
      const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(emptyResponse(204));

      await logout();
      const [url, init] = fetchMock.mock.calls[0];
      expect(url).toBe(`${AUTH_BASE}/logout`);
      expect(init?.method).toBe("POST");
      expect(init?.credentials).toBe("include");
    });

    it("logoutAll POSTs to /auth/logout-all with credentials include", async () => {
      const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(emptyResponse(204));

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
      const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(emptyResponse(401));

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

  describe("getMe", () => {
    // MYS-35: UserProfile must carry `id`. Annotating the fixture as UserProfile
    // means this object literal only typechecks once UserProfile gains `id`
    // (TS reports excess-property TS2353 until then). That compile error is the
    // RED for the frontend contract — getMe() passes JSON through unchanged at
    // runtime, so vitest alone cannot detect the missing type field.
    const profile: UserProfile = {
      id: "11111111-1111-1111-1111-111111111111",
      display_name: "Ada",
      email: "ada@example.com",
      preferred_service: "spotify",
      is_platform_admin: false,
    };

    it("GETs /api/v1/users/me (Bearer + credentials) and resolves the parsed profile on 200", async () => {
      setStoredAccessToken("my-token");
      const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(jsonResponse(200, profile));

      const resolved = await getMe();
      expect(resolved).toEqual(profile);
      // MYS-35: the user id is carried through the parsed profile verbatim. The
      // typed read below fails to compile until UserProfile declares `id`.
      const id: string = resolved.id;
      expect(id).toBe("11111111-1111-1111-1111-111111111111");

      expect(fetchMock).toHaveBeenCalledTimes(1);
      const [url, init] = fetchMock.mock.calls[0];
      expect(url).toBe(`${API_BASE}/api/v1/users/me`);
      expect(init?.credentials).toBe("include");
      const headers = new Headers(init?.headers);
      expect(headers.get("Authorization")).toBe("Bearer my-token");
    });

    it("resolves the empty-string display_name sentinel verbatim (not-yet-onboarded)", async () => {
      setStoredAccessToken("my-token");
      vi.spyOn(globalThis, "fetch").mockResolvedValue(
        jsonResponse(200, { ...profile, display_name: "" }),
      );

      await expect(getMe()).resolves.toMatchObject({ display_name: "" });
    });

    it("throws ApiError with the backend detail on a non-2xx response", async () => {
      setStoredAccessToken("my-token");
      // 401 then a failed refresh so authenticatedRequest surfaces the 401.
      vi.spyOn(globalThis, "fetch")
        .mockResolvedValueOnce(jsonResponse(401, { detail: "not authenticated" }))
        .mockResolvedValueOnce(emptyResponse(401));

      const err = await getMe().catch((e: unknown) => e);
      expect(err).toBeInstanceOf(ApiError);
      expect(err).toMatchObject({ status: 401, message: "not authenticated" });
    });

    it("throws ApiError with a generic message when the error body is not JSON", async () => {
      setStoredAccessToken("my-token");
      vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response("nope", { status: 500 }));

      await expect(getMe()).rejects.toMatchObject({
        status: 500,
        message: "request failed (500)",
      });
    });
  });

  describe("updateDisplayName", () => {
    // See the getMe fixture note above: annotated UserProfile so the `id`
    // property only typechecks once the type gains it (MYS-35).
    const profile: UserProfile = {
      id: "11111111-1111-1111-1111-111111111111",
      display_name: "Alice",
      email: "alice@example.com",
      preferred_service: null,
      is_platform_admin: false,
    };

    it("PATCHes /api/v1/users/me with a JSON body and returns the parsed profile on 200", async () => {
      setStoredAccessToken("my-token");
      const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(jsonResponse(200, profile));

      await expect(updateDisplayName("Alice")).resolves.toEqual(profile);

      expect(fetchMock).toHaveBeenCalledTimes(1);
      const [url, init] = fetchMock.mock.calls[0];
      expect(url).toBe(`${API_BASE}/api/v1/users/me`);
      expect(init?.method).toBe("PATCH");
      expect(init?.credentials).toBe("include");
      expect(init?.body).toBe(JSON.stringify({ display_name: "Alice" }));
      const headers = new Headers(init?.headers);
      expect(headers.get("Content-Type")).toBe("application/json");
      expect(headers.get("Authorization")).toBe("Bearer my-token");
    });

    it("throws ApiError with the backend detail on a 422 validation failure", async () => {
      setStoredAccessToken("my-token");
      vi.spyOn(globalThis, "fetch").mockResolvedValue(
        jsonResponse(422, { detail: "display name too long" }),
      );

      const err = await updateDisplayName("x".repeat(100)).catch((e: unknown) => e);
      expect(err).toBeInstanceOf(ApiError);
      expect(err).toMatchObject({ status: 422, message: "display name too long" });
    });
  });

  describe("createLeague", () => {
    const input = {
      name: "Friday Mixers",
      total_rounds: 6,
      votes_per_player: 3,
      description: "weekly picks",
    };

    it("POSTs /api/v1/leagues with a JSON body (Bearer + credentials) and resolves the League on 201", async () => {
      setStoredAccessToken("my-token");
      const fetchMock = vi
        .spyOn(globalThis, "fetch")
        .mockResolvedValue(jsonResponse(201, sampleLeague));

      await expect(createLeague(input)).resolves.toEqual(sampleLeague);

      expect(fetchMock).toHaveBeenCalledTimes(1);
      const [url, init] = fetchMock.mock.calls[0];
      expect(url).toBe(`${V1_BASE}/leagues`);
      expect(init?.method).toBe("POST");
      expect(init?.credentials).toBe("include");
      expect(init?.body).toBe(JSON.stringify(input));
      const headers = new Headers(init?.headers);
      expect(headers.get("Content-Type")).toBe("application/json");
      expect(headers.get("Authorization")).toBe("Bearer my-token");
    });

    it("sends only the provided fields when optional fields are omitted", async () => {
      setStoredAccessToken("my-token");
      const fetchMock = vi
        .spyOn(globalThis, "fetch")
        .mockResolvedValue(jsonResponse(201, sampleLeague));

      const minimal = { name: "Solo", total_rounds: 1 };
      await createLeague(minimal);

      const [, init] = fetchMock.mock.calls[0];
      expect(init?.body).toBe(JSON.stringify(minimal));
    });

    it("throws ApiError with the backend detail on a 422 validation failure", async () => {
      setStoredAccessToken("my-token");
      vi.spyOn(globalThis, "fetch").mockResolvedValue(
        jsonResponse(422, { detail: "total_rounds must be at least 1" }),
      );

      const err = await createLeague(input).catch((e: unknown) => e);
      expect(err).toBeInstanceOf(ApiError);
      expect(err).toMatchObject({
        status: 422,
        message: "total_rounds must be at least 1",
      });
    });

    it("throws ApiError with a generic message when the error body is not JSON", async () => {
      setStoredAccessToken("my-token");
      vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response("nope", { status: 500 }));

      await expect(createLeague(input)).rejects.toMatchObject({
        status: 500,
        message: "request failed (500)",
      });
    });
  });

  describe("getLeagues", () => {
    it("GETs /api/v1/leagues (Bearer + credentials) and resolves the array on 200", async () => {
      setStoredAccessToken("my-token");
      const fetchMock = vi
        .spyOn(globalThis, "fetch")
        .mockResolvedValue(jsonResponse(200, [sampleLeague]));

      await expect(getLeagues()).resolves.toEqual([sampleLeague]);

      expect(fetchMock).toHaveBeenCalledTimes(1);
      const [url, init] = fetchMock.mock.calls[0];
      expect(url).toBe(`${V1_BASE}/leagues`);
      expect(init?.method ?? "GET").toBe("GET");
      expect(init?.credentials).toBe("include");
      const headers = new Headers(init?.headers);
      expect(headers.get("Authorization")).toBe("Bearer my-token");
    });

    it("resolves an empty array when the user has no leagues", async () => {
      setStoredAccessToken("my-token");
      vi.spyOn(globalThis, "fetch").mockResolvedValue(jsonResponse(200, []));

      await expect(getLeagues()).resolves.toEqual([]);
    });

    it("throws ApiError with the backend detail on a non-2xx response", async () => {
      setStoredAccessToken("my-token");
      vi.spyOn(globalThis, "fetch").mockResolvedValue(jsonResponse(500, { detail: "boom" }));

      const err = await getLeagues().catch((e: unknown) => e);
      expect(err).toBeInstanceOf(ApiError);
      expect(err).toMatchObject({ status: 500, message: "boom" });
    });
  });

  describe("getLeague", () => {
    it("GETs /api/v1/leagues/{id} (Bearer + credentials) and resolves the League on 200", async () => {
      setStoredAccessToken("my-token");
      const fetchMock = vi
        .spyOn(globalThis, "fetch")
        .mockResolvedValue(jsonResponse(200, sampleLeague));

      await expect(getLeague("league-1")).resolves.toEqual(sampleLeague);

      expect(fetchMock).toHaveBeenCalledTimes(1);
      const [url, init] = fetchMock.mock.calls[0];
      expect(url).toBe(`${V1_BASE}/leagues/league-1`);
      expect(init?.method ?? "GET").toBe("GET");
      expect(init?.credentials).toBe("include");
      const headers = new Headers(init?.headers);
      expect(headers.get("Authorization")).toBe("Bearer my-token");
    });

    it("throws ApiError(404) with the backend detail when the league is not found", async () => {
      setStoredAccessToken("my-token");
      vi.spyOn(globalThis, "fetch").mockResolvedValue(
        jsonResponse(404, { detail: "league not found" }),
      );

      const err = await getLeague("missing").catch((e: unknown) => e);
      expect(err).toBeInstanceOf(ApiError);
      expect(err).toMatchObject({ status: 404, message: "league not found" });
    });

    it("throws ApiError(403) when the user is not a member", async () => {
      setStoredAccessToken("my-token");
      vi.spyOn(globalThis, "fetch").mockResolvedValue(
        jsonResponse(403, { detail: "not a member of this league" }),
      );

      const err = await getLeague("league-1").catch((e: unknown) => e);
      expect(err).toBeInstanceOf(ApiError);
      expect(err).toMatchObject({
        status: 403,
        message: "not a member of this league",
      });
    });
  });

  describe("getLeagueMembers", () => {
    const members: LeagueMember[] = [
      {
        user_id: "user-1",
        display_name: "Ada",
        joined_at: "2026-06-01T00:00:00Z",
        is_organizer: true,
      },
      {
        user_id: "user-2",
        display_name: "Bo",
        joined_at: "2026-06-02T00:00:00Z",
        is_organizer: false,
      },
    ];

    it("GETs /api/v1/leagues/{id}/members (Bearer + credentials) and resolves the array on 200", async () => {
      setStoredAccessToken("my-token");
      const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(jsonResponse(200, members));

      await expect(getLeagueMembers("league-1")).resolves.toEqual(members);

      expect(fetchMock).toHaveBeenCalledTimes(1);
      const [url, init] = fetchMock.mock.calls[0];
      expect(url).toBe(`${V1_BASE}/leagues/league-1/members`);
      expect(init?.method ?? "GET").toBe("GET");
      expect(init?.credentials).toBe("include");
      const headers = new Headers(init?.headers);
      expect(headers.get("Authorization")).toBe("Bearer my-token");
    });

    it("throws ApiError with the backend detail on a non-2xx response", async () => {
      setStoredAccessToken("my-token");
      vi.spyOn(globalThis, "fetch").mockResolvedValue(
        jsonResponse(403, { detail: "not a member of this league" }),
      );

      const err = await getLeagueMembers("league-1").catch((e: unknown) => e);
      expect(err).toBeInstanceOf(ApiError);
      expect(err).toMatchObject({
        status: 403,
        message: "not a member of this league",
      });
    });
  });

  describe("updateLeague", () => {
    it("PATCHes /api/v1/leagues/{id} with a JSON body (Bearer + credentials) and resolves the League on 200", async () => {
      setStoredAccessToken("my-token");
      const updated: League = { ...sampleLeague, name: "Saturday Mixers" };
      const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(jsonResponse(200, updated));

      const input = { name: "Saturday Mixers" };
      await expect(updateLeague("league-1", input)).resolves.toEqual(updated);

      expect(fetchMock).toHaveBeenCalledTimes(1);
      const [url, init] = fetchMock.mock.calls[0];
      expect(url).toBe(`${V1_BASE}/leagues/league-1`);
      expect(init?.method).toBe("PATCH");
      expect(init?.credentials).toBe("include");
      expect(init?.body).toBe(JSON.stringify(input));
      const headers = new Headers(init?.headers);
      expect(headers.get("Content-Type")).toBe("application/json");
      expect(headers.get("Authorization")).toBe("Bearer my-token");
    });

    it("sends an explicit null description in the body", async () => {
      setStoredAccessToken("my-token");
      const fetchMock = vi
        .spyOn(globalThis, "fetch")
        .mockResolvedValue(jsonResponse(200, { ...sampleLeague, description: null }));

      const input = { description: null };
      await updateLeague("league-1", input);

      const [, init] = fetchMock.mock.calls[0];
      expect(init?.body).toBe(JSON.stringify(input));
    });

    it("throws ApiError(409) with the backend detail when total_rounds is below current_round", async () => {
      setStoredAccessToken("my-token");
      vi.spyOn(globalThis, "fetch").mockResolvedValue(
        jsonResponse(409, { detail: "total_rounds cannot be below current_round" }),
      );

      const err = await updateLeague("league-1", { total_rounds: 1 }).catch((e: unknown) => e);
      expect(err).toBeInstanceOf(ApiError);
      expect(err).toMatchObject({
        status: 409,
        message: "total_rounds cannot be below current_round",
      });
    });
  });

  describe("removeMember", () => {
    it("DELETEs /api/v1/leagues/{leagueId}/members/{userId} (Bearer + credentials) and resolves undefined on 204", async () => {
      setStoredAccessToken("my-token");
      const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(emptyResponse(204));

      await expect(removeMember("league-1", "user-2")).resolves.toBeUndefined();

      expect(fetchMock).toHaveBeenCalledTimes(1);
      const [url, init] = fetchMock.mock.calls[0];
      expect(url).toBe(`${V1_BASE}/leagues/league-1/members/user-2`);
      expect(init?.method).toBe("DELETE");
      expect(init?.credentials).toBe("include");
      const headers = new Headers(init?.headers);
      expect(headers.get("Authorization")).toBe("Bearer my-token");
    });

    it("throws ApiError(409) when attempting to remove the organizer", async () => {
      setStoredAccessToken("my-token");
      vi.spyOn(globalThis, "fetch").mockResolvedValue(
        jsonResponse(409, { detail: "cannot remove the organizer" }),
      );

      const err = await removeMember("league-1", "user-1").catch((e: unknown) => e);
      expect(err).toBeInstanceOf(ApiError);
      expect(err).toMatchObject({
        status: 409,
        message: "cannot remove the organizer",
      });
    });

    it("throws ApiError(403) when the caller is not the organizer", async () => {
      setStoredAccessToken("my-token");
      vi.spyOn(globalThis, "fetch").mockResolvedValue(
        jsonResponse(403, { detail: "organizer only" }),
      );

      const err = await removeMember("league-1", "user-2").catch((e: unknown) => e);
      expect(err).toBeInstanceOf(ApiError);
      expect(err).toMatchObject({ status: 403, message: "organizer only" });
    });
  });

  describe("createInvite", () => {
    const invite: Invite = {
      id: "invite-1",
      league_id: "league-1",
      token: "abc123",
      created_by: "user-1",
      created_at: "2026-06-03T00:00:00Z",
      expires_at: null,
    };

    it("POSTs /api/v1/leagues/{leagueId}/invites (Bearer + credentials) and resolves the Invite on 201", async () => {
      setStoredAccessToken("my-token");
      const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(jsonResponse(201, invite));

      await expect(createInvite("league-1")).resolves.toEqual(invite);

      expect(fetchMock).toHaveBeenCalledTimes(1);
      const [url, init] = fetchMock.mock.calls[0];
      expect(url).toBe(`${V1_BASE}/leagues/league-1/invites`);
      expect(init?.method).toBe("POST");
      expect(init?.credentials).toBe("include");
      const headers = new Headers(init?.headers);
      expect(headers.get("Authorization")).toBe("Bearer my-token");
    });

    it("throws ApiError with the backend detail on a non-2xx response", async () => {
      setStoredAccessToken("my-token");
      vi.spyOn(globalThis, "fetch").mockResolvedValue(
        jsonResponse(403, { detail: "not a member of this league" }),
      );

      const err = await createInvite("league-1").catch((e: unknown) => e);
      expect(err).toBeInstanceOf(ApiError);
      expect(err).toMatchObject({
        status: 403,
        message: "not a member of this league",
      });
    });
  });

  describe("getInvitePreview", () => {
    const preview: InvitePreview = {
      league_name: "Friday Mixers",
      member_count: 4,
    };

    it("GETs /api/v1/invites/{token} UNAUTHENTICATED (no Authorization header) and resolves the preview on 200", async () => {
      // Deliberately no token set: the preview is a public, unauthenticated read.
      const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(jsonResponse(200, preview));

      await expect(getInvitePreview("plain-token")).resolves.toEqual(preview);

      expect(fetchMock).toHaveBeenCalledTimes(1);
      const [url, init] = fetchMock.mock.calls[0];
      expect(url).toBe(`${V1_BASE}/invites/plain-token`);
      expect(init?.method ?? "GET").toBe("GET");
      const headers = new Headers(init?.headers);
      expect(headers.get("Authorization")).toBeNull();
    });

    it("does NOT attach an Authorization header even when an access token is set", async () => {
      setStoredAccessToken("my-token");
      const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(jsonResponse(200, preview));

      await getInvitePreview("plain-token");

      const [, init] = fetchMock.mock.calls[0];
      const headers = new Headers(init?.headers);
      expect(headers.get("Authorization")).toBeNull();
    });

    it("URL-encodes the token in the path", async () => {
      const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(jsonResponse(200, preview));

      const token = "weird/ token";
      await getInvitePreview(token);

      const [url] = fetchMock.mock.calls[0];
      expect(url).toBe(`${V1_BASE}/invites/${encodeURIComponent(token)}`);
    });

    it("throws ApiError(404) when the invite is not found", async () => {
      vi.spyOn(globalThis, "fetch").mockResolvedValue(
        jsonResponse(404, { detail: "invite not found" }),
      );

      const err = await getInvitePreview("missing").catch((e: unknown) => e);
      expect(err).toBeInstanceOf(ApiError);
      expect(err).toMatchObject({ status: 404, message: "invite not found" });
    });
  });

  describe("acceptInvite", () => {
    it("POSTs /api/v1/invites/{token}/accept (Bearer + credentials) and resolves the League on 200", async () => {
      setStoredAccessToken("my-token");
      const fetchMock = vi
        .spyOn(globalThis, "fetch")
        .mockResolvedValue(jsonResponse(200, sampleLeague));

      await expect(acceptInvite("plain-token")).resolves.toEqual(sampleLeague);

      expect(fetchMock).toHaveBeenCalledTimes(1);
      const [url, init] = fetchMock.mock.calls[0];
      expect(url).toBe(`${V1_BASE}/invites/plain-token/accept`);
      expect(init?.method).toBe("POST");
      expect(init?.credentials).toBe("include");
      const headers = new Headers(init?.headers);
      expect(headers.get("Authorization")).toBe("Bearer my-token");
    });

    it("URL-encodes the token in the path", async () => {
      setStoredAccessToken("my-token");
      const fetchMock = vi
        .spyOn(globalThis, "fetch")
        .mockResolvedValue(jsonResponse(200, sampleLeague));

      const token = "weird/ token";
      await acceptInvite(token);

      const [url] = fetchMock.mock.calls[0];
      expect(url).toBe(`${V1_BASE}/invites/${encodeURIComponent(token)}/accept`);
    });

    it("throws ApiError(409) when the user is already a member", async () => {
      setStoredAccessToken("my-token");
      vi.spyOn(globalThis, "fetch").mockResolvedValue(
        jsonResponse(409, { detail: "already a member" }),
      );

      const err = await acceptInvite("plain-token").catch((e: unknown) => e);
      expect(err).toBeInstanceOf(ApiError);
      expect(err).toMatchObject({ status: 409, message: "already a member" });
    });

    it("surfaces ApiError when the 401 silent-refresh path fails", async () => {
      setStoredAccessToken("my-token");
      // 401 then a failed refresh so authenticatedRequest surfaces the 401.
      vi.spyOn(globalThis, "fetch")
        .mockResolvedValueOnce(jsonResponse(401, { detail: "not authenticated" }))
        .mockResolvedValueOnce(emptyResponse(401));

      const err = await acceptInvite("plain-token").catch((e: unknown) => e);
      expect(err).toBeInstanceOf(ApiError);
      expect(err).toMatchObject({ status: 401, message: "not authenticated" });
    });
  });

  describe("castVotes", () => {
    const votes: Votes = {
      round_id: "r1",
      submission_ids: ["s1", "s2"],
      count: 2,
      votes_per_player: 3,
    };

    it("POSTs /api/v1/rounds/{id}/votes with the submission_ids body (Bearer + credentials) and resolves the Votes on 200", async () => {
      setStoredAccessToken("my-token");
      const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(jsonResponse(200, votes));

      await expect(castVotes("r1", ["s1", "s2"])).resolves.toEqual(votes);

      expect(fetchMock).toHaveBeenCalledTimes(1);
      const [url, init] = fetchMock.mock.calls[0];
      expect(url).toBe(`${V1_BASE}/rounds/r1/votes`);
      expect(init?.method).toBe("POST");
      expect(init?.credentials).toBe("include");
      expect(init?.body).toBe(JSON.stringify({ submission_ids: ["s1", "s2"] }));
      const headers = new Headers(init?.headers);
      expect(headers.get("Content-Type")).toBe("application/json");
      expect(headers.get("Authorization")).toBe("Bearer my-token");
    });

    it("throws ApiError(409) when casting an empty set", async () => {
      setStoredAccessToken("my-token");
      vi.spyOn(globalThis, "fetch").mockResolvedValue(
        jsonResponse(409, { detail: "you must vote for at least one song" }),
      );

      const err = await castVotes("r1", []).catch((e: unknown) => e);
      expect(err).toBeInstanceOf(ApiError);
      expect(err).toMatchObject({
        status: 409,
        message: "you must vote for at least one song",
      });
    });

    it("throws ApiError(403) when voting for your own song", async () => {
      setStoredAccessToken("my-token");
      vi.spyOn(globalThis, "fetch").mockResolvedValue(
        jsonResponse(403, { detail: "you can't vote for your own song" }),
      );

      const err = await castVotes("r1", ["mine"]).catch((e: unknown) => e);
      expect(err).toBeInstanceOf(ApiError);
      expect(err).toMatchObject({
        status: 403,
        message: "you can't vote for your own song",
      });
    });

    it("throws ApiError with a generic message when the error body is not JSON", async () => {
      setStoredAccessToken("my-token");
      vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response("nope", { status: 500 }));

      await expect(castVotes("r1", ["s1"])).rejects.toMatchObject({
        status: 500,
        message: "request failed (500)",
      });
    });
  });

  describe("getMyVotes", () => {
    const votes: Votes = {
      round_id: "r1",
      submission_ids: ["s1"],
      count: 1,
      votes_per_player: 3,
    };

    it("GETs /api/v1/rounds/{id}/votes/mine (Bearer + credentials) and resolves the Votes on 200", async () => {
      setStoredAccessToken("my-token");
      const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(jsonResponse(200, votes));

      await expect(getMyVotes("r1")).resolves.toEqual(votes);

      expect(fetchMock).toHaveBeenCalledTimes(1);
      const [url, init] = fetchMock.mock.calls[0];
      expect(url).toBe(`${V1_BASE}/rounds/r1/votes/mine`);
      expect(init?.method ?? "GET").toBe("GET");
      expect(init?.credentials).toBe("include");
      const headers = new Headers(init?.headers);
      expect(headers.get("Authorization")).toBe("Bearer my-token");
    });

    it("resolves the empty-set case when nothing has been cast", async () => {
      setStoredAccessToken("my-token");
      const empty: Votes = {
        round_id: "r1",
        submission_ids: [],
        count: 0,
        votes_per_player: 3,
      };
      vi.spyOn(globalThis, "fetch").mockResolvedValue(jsonResponse(200, empty));

      await expect(getMyVotes("r1")).resolves.toEqual(empty);
    });

    it("throws ApiError with the backend detail on a non-2xx response", async () => {
      setStoredAccessToken("my-token");
      vi.spyOn(globalThis, "fetch").mockResolvedValue(
        jsonResponse(403, { detail: "not a member of this league" }),
      );

      const err = await getMyVotes("r1").catch((e: unknown) => e);
      expect(err).toBeInstanceOf(ApiError);
      expect(err).toMatchObject({
        status: 403,
        message: "not a member of this league",
      });
    });
  });

  describe("addNote", () => {
    const note: Note = {
      id: "n1",
      submission_id: "sub-1",
      round_id: "r1",
      author_id: "user-1",
      author_display_name: "Ada",
      body: "lovely pick",
      created_at: "2026-06-04T00:00:00Z",
    };

    it("POSTs /api/v1/submissions/{id}/notes with the body (Bearer + credentials) and resolves the Note on 201", async () => {
      setStoredAccessToken("my-token");
      const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(jsonResponse(201, note));

      await expect(addNote("sub-1", "lovely pick")).resolves.toEqual(note);

      expect(fetchMock).toHaveBeenCalledTimes(1);
      const [url, init] = fetchMock.mock.calls[0];
      expect(url).toBe(`${V1_BASE}/submissions/sub-1/notes`);
      expect(init?.method).toBe("POST");
      expect(init?.credentials).toBe("include");
      expect(init?.body).toBe(JSON.stringify({ body: "lovely pick" }));
      const headers = new Headers(init?.headers);
      expect(headers.get("Content-Type")).toBe("application/json");
      expect(headers.get("Authorization")).toBe("Bearer my-token");
    });

    it("throws ApiError(409) when the round is not open for voting", async () => {
      setStoredAccessToken("my-token");
      vi.spyOn(globalThis, "fetch").mockResolvedValue(
        jsonResponse(409, { detail: "notes are only allowed while voting is open" }),
      );

      const err = await addNote("sub-1", "lovely pick").catch((e: unknown) => e);
      expect(err).toBeInstanceOf(ApiError);
      expect(err).toMatchObject({
        status: 409,
        message: "notes are only allowed while voting is open",
      });
    });

    it("throws ApiError with a generic message when the error body is not JSON", async () => {
      setStoredAccessToken("my-token");
      vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response("nope", { status: 500 }));

      await expect(addNote("sub-1", "lovely pick")).rejects.toMatchObject({
        status: 500,
        message: "request failed (500)",
      });
    });
  });

  describe("getNotes", () => {
    const notes: Note[] = [
      {
        id: "n1",
        submission_id: "sub-1",
        round_id: "r1",
        author_id: "user-1",
        author_display_name: "Ada",
        body: "lovely pick",
        created_at: "2026-06-04T00:00:00Z",
      },
      {
        id: "n2",
        submission_id: "sub-1",
        round_id: "r1",
        author_id: "user-2",
        author_display_name: "Bo",
        body: "this slaps",
        created_at: "2026-06-04T01:00:00Z",
      },
    ];

    it("GETs /api/v1/submissions/{id}/notes (Bearer + credentials) and resolves the array on 200", async () => {
      setStoredAccessToken("my-token");
      const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(jsonResponse(200, notes));

      await expect(getNotes("sub-1")).resolves.toEqual(notes);

      expect(fetchMock).toHaveBeenCalledTimes(1);
      const [url, init] = fetchMock.mock.calls[0];
      expect(url).toBe(`${V1_BASE}/submissions/sub-1/notes`);
      expect(init?.method ?? "GET").toBe("GET");
      expect(init?.credentials).toBe("include");
      const headers = new Headers(init?.headers);
      expect(headers.get("Authorization")).toBe("Bearer my-token");
    });

    it("resolves an empty array when the submission has no notes", async () => {
      setStoredAccessToken("my-token");
      vi.spyOn(globalThis, "fetch").mockResolvedValue(jsonResponse(200, []));

      await expect(getNotes("sub-1")).resolves.toEqual([]);
    });

    it("throws ApiError with the backend detail on a non-2xx response", async () => {
      setStoredAccessToken("my-token");
      vi.spyOn(globalThis, "fetch").mockResolvedValue(
        jsonResponse(403, { detail: "not a member of this league" }),
      );

      const err = await getNotes("sub-1").catch((e: unknown) => e);
      expect(err).toBeInstanceOf(ApiError);
      expect(err).toMatchObject({
        status: 403,
        message: "not a member of this league",
      });
    });
  });

  describe("getResults", () => {
    const sampleResults: RoundResults = {
      round_id: "r1",
      round_number: 1,
      theme: "late summer feels",
      state: "closed",
      viewer_is_vibing: false,
      winners: [],
      picks: [],
      submissions: [
        {
          submission_id: "sub-1",
          user_id: "user-2",
          submitter_display_name: "Bo",
          isrc: "I1",
          title: "Debaser",
          artist: "Pixies",
          album: null,
          album_art_url: null,
          platforms: { spotify: "https://open.spotify.com/track/x" },
          submitter_note: "a banger",
          vote_count: 3,
          notes: [{ body: "this slaps", author_display_name: "Ada", created_at: "x" }],
        },
      ],
      leaderboard: [{ user_id: "user-2", display_name: "Bo", vote_count: 3, rank: 1 }],
      most_noted: {
        note_count: 1,
        winners: [
          {
            submission_id: "sub-1",
            title: "Debaser",
            artist: "Pixies",
            note_count: 1,
            notes: [{ body: "this slaps", author_display_name: "Ada", created_at: "x" }],
          },
        ],
      },
    };

    it("GETs /api/v1/rounds/{id}/results (Bearer + credentials) and resolves the results on 200", async () => {
      setStoredAccessToken("my-token");
      const fetchMock = vi
        .spyOn(globalThis, "fetch")
        .mockResolvedValue(jsonResponse(200, sampleResults));

      await expect(getResults("r1")).resolves.toEqual(sampleResults);

      expect(fetchMock).toHaveBeenCalledTimes(1);
      const [url, init] = fetchMock.mock.calls[0];
      expect(url).toBe(`${V1_BASE}/rounds/r1/results`);
      expect(init?.method ?? "GET").toBe("GET");
      expect(init?.credentials).toBe("include");
      const headers = new Headers(init?.headers);
      expect(headers.get("Authorization")).toBe("Bearer my-token");
    });

    it("throws ApiError(409) when the round is not yet closed", async () => {
      setStoredAccessToken("my-token");
      vi.spyOn(globalThis, "fetch").mockResolvedValue(
        jsonResponse(409, { detail: "results are available once the round closes" }),
      );

      const err = await getResults("r1").catch((e: unknown) => e);
      expect(err).toBeInstanceOf(ApiError);
      expect(err).toMatchObject({
        status: 409,
        message: "results are available once the round closes",
      });
    });

    it("throws ApiError with a generic message when the error body is not JSON", async () => {
      setStoredAccessToken("my-token");
      vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response("nope", { status: 500 }));

      await expect(getResults("r1")).rejects.toMatchObject({
        status: 500,
        message: "request failed (500)",
      });
    });
  });
});
