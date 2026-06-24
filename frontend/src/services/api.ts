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

// Default to the 127.0.0.1 loopback (not "localhost"): the app keeps every
// origin on one host so the session cookie survives the Spotify OAuth redirect
// (MYS-85), and Spotify rejects "localhost" redirect URIs.
const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://127.0.0.1:8000";
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
 */
export async function requestMagicLink(email: string): Promise<void> {
  const res = await fetch(`${AUTH_BASE}/request`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email }),
  });
  if (!res.ok) {
    throw new ApiError(res.status, await readErrorMessage(res));
  }
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

export { ApiError };
