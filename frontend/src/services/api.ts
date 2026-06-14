/**
 * API client for the MysteryMixClub backend.
 *
 * Token storage rules (technical-design §5 / §9):
 *  - The access token lives in memory ONLY (the module-level `accessToken`
 *    variable below). It is never written to localStorage, sessionStorage, or
 *    a client-set cookie.
 *  - The refresh token is an HttpOnly cookie the browser manages; we never read
 *    or set it. Endpoints that depend on it use `credentials: 'include'` so the
 *    cookie is sent on the cross-origin (but same-site) request to :8000.
 */

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";
const AUTH_BASE = `${API_BASE_URL}/api/v1/auth`;

/** In-memory access token. Lost on full page reload by design — the on-mount
 *  silent refresh restores the session from the HttpOnly cookie. */
let accessToken: string | null = null;

export function getAccessToken(): string | null {
  return accessToken;
}

export function setStoredAccessToken(token: string | null): void {
  accessToken = token;
}

type TokenResponse = {
  access_token: string;
  token_type: string;
};

/** Current user profile (GET /api/v1/users/me). A non-empty `display_name`
 *  means the user has completed onboarding; "" is the not-yet-onboarded
 *  sentinel. */
export type UserProfile = {
  id: string;
  display_name: string;
  email: string;
  preferred_service: string | null;
  default_vibe_mode: boolean;
};

class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

async function readErrorMessage(res: Response): Promise<string> {
  try {
    const data = (await res.json()) as { detail?: unknown };
    if (typeof data.detail === "string") return data.detail;
  } catch {
    // Non-JSON body; fall through to a generic message.
  }
  return `request failed (${res.status})`;
}

/**
 * Request a magic link. Returns a neutral result regardless of whether the
 * email is registered — the backend responds 200 with a neutral message.
 *
 * Outside production the backend also returns `dev_token` so the UI can show a
 * clickable sign-in link for testing; it is absent in production.
 */
export async function requestMagicLink(email: string): Promise<{ devToken: string | null }> {
  const res = await fetch(`${AUTH_BASE}/request`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email }),
  });
  if (!res.ok) {
    throw new ApiError(res.status, await readErrorMessage(res));
  }
  const data = (await res.json()) as { dev_token?: string | null };
  return { devToken: data.dev_token ?? null };
}

/**
 * Verify a magic-link token. On success the backend sets the HttpOnly refresh
 * cookie and returns the access token. Requires `credentials: 'include'` so the
 * Set-Cookie is accepted.
 */
export async function verifyToken(token: string): Promise<{ access_token: string }> {
  const res = await fetch(`${AUTH_BASE}/verify?token=${encodeURIComponent(token)}`, {
    method: "GET",
    credentials: "include",
  });
  if (!res.ok) {
    throw new ApiError(res.status, await readErrorMessage(res));
  }
  const data = (await res.json()) as TokenResponse;
  return { access_token: data.access_token };
}

/**
 * Exchange the HttpOnly refresh cookie for a fresh access token. Returns the
 * new token on success, or null when there is no valid session (401). Any other
 * failure also resolves to null so callers can treat it as "unauthenticated".
 */
export async function refresh(): Promise<{ access_token: string } | null> {
  try {
    const res = await fetch(`${AUTH_BASE}/refresh`, {
      method: "POST",
      credentials: "include",
    });
    if (!res.ok) return null;
    const data = (await res.json()) as TokenResponse;
    return { access_token: data.access_token };
  } catch {
    return null;
  }
}

/** Invalidate the current session and clear the refresh cookie. Idempotent. */
export async function logout(): Promise<void> {
  await fetch(`${AUTH_BASE}/logout`, {
    method: "POST",
    credentials: "include",
  });
}

/** Invalidate all sessions for the current user. */
export async function logoutAll(): Promise<void> {
  await fetch(`${AUTH_BASE}/logout-all`, {
    method: "POST",
    credentials: "include",
  });
}

type RequestOptions = RequestInit & {
  /** Set false to skip the silent-refresh retry (used internally to avoid loops). */
  retryOnUnauthorized?: boolean;
};

/**
 * Authenticated fetch wrapper. Attaches `Authorization: Bearer <token>` when an
 * access token is present and, on a 401, performs ONE silent refresh and retries
 * the original request with the new token. If the refresh fails, the in-memory
 * token is cleared and the 401 is surfaced to the caller (unauthenticated).
 *
 * No Bearer-protected endpoints exist yet, but this is the deliverable
 * "silent refresh on authenticated requests" and is ready for /users/me etc.
 *
 * `path` is relative to the API base, e.g. "/api/v1/users/me".
 */
export async function authenticatedRequest(
  path: string,
  options: RequestOptions = {},
): Promise<Response> {
  const { retryOnUnauthorized = true, headers, ...rest } = options;

  const buildHeaders = (): HeadersInit => {
    const merged = new Headers(headers);
    if (accessToken) merged.set("Authorization", `Bearer ${accessToken}`);
    return merged;
  };

  const res = await fetch(`${API_BASE_URL}${path}`, {
    ...rest,
    credentials: "include",
    headers: buildHeaders(),
  });

  if (res.status !== 401 || !retryOnUnauthorized) {
    return res;
  }

  // One silent refresh attempt, then retry the original request once.
  const refreshed = await refresh();
  if (!refreshed) {
    accessToken = null;
    return res;
  }
  accessToken = refreshed.access_token;

  return fetch(`${API_BASE_URL}${path}`, {
    ...rest,
    credentials: "include",
    headers: buildHeaders(),
  });
}

/** Fetch the current user's profile. Bearer-auth via authenticatedRequest. */
export async function getMe(): Promise<UserProfile> {
  const res = await authenticatedRequest("/api/v1/users/me");
  if (!res.ok) {
    throw new ApiError(res.status, await readErrorMessage(res));
  }
  return (await res.json()) as UserProfile;
}

/** Set the current user's display name (1–50 chars, trimmed server-side).
 *  Returns the updated profile. */
export async function updateDisplayName(displayName: string): Promise<UserProfile> {
  const res = await authenticatedRequest("/api/v1/users/me", {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ display_name: displayName }),
  });
  if (!res.ok) {
    throw new ApiError(res.status, await readErrorMessage(res));
  }
  return (await res.json()) as UserProfile;
}

/** A league as returned by the backend (GET/POST /api/v1/leagues). */
export type League = {
  id: string;
  name: string;
  description: string | null;
  organizer_id: string;
  total_rounds: number;
  votes_per_player: number;
  current_round: number;
  state: string;
  created_at: string;
  completed_at: string | null;
};

/** A member of a league (GET /api/v1/leagues/:id/members). */
export type LeagueMember = {
  user_id: string;
  display_name: string;
  joined_at: string;
  is_organizer: boolean;
};

/** An invite to a league (POST /api/v1/leagues/:id/invites). */
export type Invite = {
  id: string;
  league_id: string;
  token: string;
  created_by: string;
  created_at: string;
  expires_at: string | null;
};

/** Public preview of a league shown before joining (GET /api/v1/invites/:token). */
export type InvitePreview = {
  league_name: string;
  member_count: number;
};

/** Create a new league. Returns the created League on 201. Only the provided
 *  fields are serialized; JSON.stringify drops undefined optional keys. */
export async function createLeague(input: {
  name: string;
  total_rounds: number;
  votes_per_player?: number;
  description?: string;
}): Promise<League> {
  const res = await authenticatedRequest("/api/v1/leagues", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
  if (!res.ok) {
    throw new ApiError(res.status, await readErrorMessage(res));
  }
  return (await res.json()) as League;
}

/** Get all leagues for the current user. */
export async function getLeagues(): Promise<League[]> {
  const res = await authenticatedRequest("/api/v1/leagues");
  if (!res.ok) {
    throw new ApiError(res.status, await readErrorMessage(res));
  }
  return (await res.json()) as League[];
}

/** Get a single league by id. */
export async function getLeague(id: string): Promise<League> {
  const res = await authenticatedRequest(`/api/v1/leagues/${id}`);
  if (!res.ok) {
    throw new ApiError(res.status, await readErrorMessage(res));
  }
  return (await res.json()) as League;
}

/** Get the members of a league. */
export async function getLeagueMembers(id: string): Promise<LeagueMember[]> {
  const res = await authenticatedRequest(`/api/v1/leagues/${id}/members`);
  if (!res.ok) {
    throw new ApiError(res.status, await readErrorMessage(res));
  }
  return (await res.json()) as LeagueMember[];
}

/** Update a league (organizer only). An explicit null description is sent as-is;
 *  only undefined keys are dropped by JSON.stringify. Returns the updated League. */
export async function updateLeague(
  id: string,
  input: { name?: string; description?: string | null; total_rounds?: number },
): Promise<League> {
  const res = await authenticatedRequest(`/api/v1/leagues/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
  if (!res.ok) {
    throw new ApiError(res.status, await readErrorMessage(res));
  }
  return (await res.json()) as League;
}

/** Remove a member from a league (organizer only). Resolves on 204. */
export async function removeMember(leagueId: string, userId: string): Promise<void> {
  const res = await authenticatedRequest(
    `/api/v1/leagues/${leagueId}/members/${userId}`,
    { method: "DELETE" },
  );
  if (!res.ok) {
    throw new ApiError(res.status, await readErrorMessage(res));
  }
}

/** Generate an invite link for a league (organizer or member). Returns the Invite. */
export async function createInvite(leagueId: string): Promise<Invite> {
  const res = await authenticatedRequest(`/api/v1/leagues/${leagueId}/invites`, {
    method: "POST",
  });
  if (!res.ok) {
    throw new ApiError(res.status, await readErrorMessage(res));
  }
  return (await res.json()) as Invite;
}

/** Validate an invite token and return a public league preview. Unauthenticated:
 *  a plain fetch with no Authorization header, since anyone with the link may
 *  view the preview before joining. */
export async function getInvitePreview(token: string): Promise<InvitePreview> {
  const res = await fetch(`${API_BASE_URL}/api/v1/invites/${encodeURIComponent(token)}`);
  if (!res.ok) {
    throw new ApiError(res.status, await readErrorMessage(res));
  }
  return (await res.json()) as InvitePreview;
}

/** Join a league via invite token. Returns the joined League on 200. */
export async function acceptInvite(token: string): Promise<League> {
  const res = await authenticatedRequest(
    `/api/v1/invites/${encodeURIComponent(token)}/accept`,
    { method: "POST" },
  );
  if (!res.ok) {
    throw new ApiError(res.status, await readErrorMessage(res));
  }
  return (await res.json()) as League;
}

export { ApiError };
