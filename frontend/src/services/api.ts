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

/** Current user profile (GET /api/v1/users/me). A non-empty `display_name`
 *  means the user has completed onboarding; "" is the not-yet-onboarded
 *  sentinel. */
export type UserProfile = {
  id: string;
  display_name: string;
  email: string;
  preferred_service: string | null;
  /** True for platform admins (email in the server's SEED_ADMIN_EMAILS). Gates
   *  the /admin page and its nav entry. */
  is_platform_admin: boolean;
  /** True once the user has accepted the current Terms of Service / Privacy
   *  Policy (MYS-183). Drives the onboarding/consent gate. */
  tos_accepted: boolean;
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
 * When the request comes from a shareable invite link, pass `inviteToken` so the
 * backend can both gate signup on it (a new account requires a valid invite) and
 * carry it into the verify link to auto-join the league. The dev verify link the
 * UI builds must append `&invite=<inviteToken>` to match.
 *
 * Outside production the backend also returns `dev_token` so the UI can show a
 * clickable sign-in link for testing; it is absent in production.
 */
export async function requestMagicLink(
  email: string,
  inviteToken?: string | null,
): Promise<{ devToken: string | null }> {
  const res = await fetch(`${AUTH_BASE}/request`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    // JSON.stringify drops an undefined value, so an absent invite token simply
    // isn't sent — keeping the no-invite request body identical to before.
    body: JSON.stringify({ email, invite_token: inviteToken ?? undefined }),
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
export async function verifyToken(
  token: string,
  invite?: string | null,
): Promise<{ access_token: string }> {
  const params = new URLSearchParams({ token });
  // A new account requires a valid invite; an existing user with an invite is
  // auto-joined to that league. Absent invite → plain verify (existing users).
  if (invite) params.set("invite", invite);
  const res = await fetch(`${AUTH_BASE}/verify?${params.toString()}`, {
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

/** Accept the Terms of Service / Privacy Policy, optionally setting the
 *  display name in the same request (MYS-183 onboarding/consent gate). The
 *  server stamps its own acceptance timestamp — nothing client-supplied is
 *  trusted for that. Returns the updated profile. */
export async function acceptTerms(displayName?: string): Promise<UserProfile> {
  const body: Record<string, unknown> = { accept_terms: true };
  if (displayName !== undefined) body.display_name = displayName;
  const res = await authenticatedRequest("/api/v1/users/me", {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
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

/** Set the current user's preferred streaming service (or null to clear). */
export async function updatePreferredService(
  service: "spotify" | "youtube" | "deezer" | null,
): Promise<UserProfile> {
  const res = await authenticatedRequest("/api/v1/users/me", {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ preferred_service: service }),
  });
  if (!res.ok) {
    throw new ApiError(res.status, await readErrorMessage(res));
  }
  return (await res.json()) as UserProfile;
}

/** Delete the current user's account (right to be forgotten). Throws 409 if
 *  the user organizes an active league. */
export async function deleteAccount(): Promise<void> {
  const res = await authenticatedRequest("/api/v1/users/me", { method: "DELETE" });
  if (!res.ok) {
    throw new ApiError(res.status, await readErrorMessage(res));
  }
}

/** A league as returned by the backend (GET/POST /api/v1/leagues). */
export type League = {
  id: string;
  name: string;
  description: string | null;
  organizer_id: string;
  total_rounds: number;
  votes_per_player: number;
  /** How many songs a player may submit per round (MYS-116). Fixed at league
   *  setup; 1 = classic one-song behaviour, max 5. */
  songs_per_submission: number;
  current_round: number;
  state: string;
  /** Admin-set default participation mode for the league (MYS-112). A member's
   *  own setting lives on their membership (getMyMembership), not here. */
  default_vibe_mode: boolean;
  /** Hour-granular deadline windows stamped onto each round when it opens
   *  (MYS-158/160). Bounds: 4–168 hours (1 week). */
  submission_window_hours: number;
  voting_window_hours: number;
  created_at: string;
  completed_at: string | null;
};

/** The caller's own per-league participation setting (GET/PATCH
 *  /leagues/:id/membership). Vibing is private — this is only ever the caller's
 *  own setting, never another member's. */
export type Membership = {
  league_id: string;
  user_id: string;
  vibe_mode: boolean;
};

/** A member of a league (GET /api/v1/leagues/:id/members). `is_admin` is true
 *  for the fixed organizer or anyone holding the co-organizer `"admin"` role
 *  (MYS-99). */
export type LeagueMember = {
  user_id: string;
  display_name: string;
  joined_at: string;
  is_organizer: boolean;
  is_admin: boolean;
};

/** An invite (POST /api/v1/leagues/:id/invites, or POST /api/v1/admin/invites
 *  for a platform invite). ``league_id`` is null for a platform invite
 *  (MYS-182): grants signup only, no league attachment. */
export type Invite = {
  id: string;
  league_id: string | null;
  token: string;
  created_by: string;
  created_at: string;
  expires_at: string | null;
};

/** Public preview of an invite shown before joining (GET /api/v1/invites/:token).
 *  ``league_id``/``league_name``/``member_count`` are null for a platform
 *  invite (MYS-182) — there's no league to preview, just a signup grant. */
export type InvitePreview = {
  league_id: string | null;
  league_name: string | null;
  member_count: number | null;
  /** True when the viewer is already an active member of this league — the
   *  caller should redirect straight in rather than showing the join screen,
   *  most relevant on an otherwise-expired link (MYS-181). Always false for
   *  a platform invite. */
  already_member: boolean;
};

/** Create a new league. Returns the created League on 201. Only the provided
 *  fields are serialized; JSON.stringify drops undefined optional keys. */
export async function createLeague(input: {
  name: string;
  total_rounds: number;
  votes_per_player?: number;
  songs_per_submission?: number;
  description?: string;
  default_vibe_mode?: boolean;
  submission_window_hours?: number;
  voting_window_hours?: number;
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

/** All-time vote leaderboard for a league (MYS-157): ranked members by total
 *  votes received across all closed rounds, with 0-vote members included. */
export async function getLeagueLeaderboard(id: string): Promise<LeaderboardEntry[]> {
  const res = await authenticatedRequest(`/api/v1/leagues/${id}/leaderboard`);
  if (!res.ok) {
    throw new ApiError(res.status, await readErrorMessage(res));
  }
  return (await res.json()) as LeaderboardEntry[];
}

/** Update a league (organizer only). An explicit null description is sent as-is;
 *  only undefined keys are dropped by JSON.stringify. Returns the updated League. */
export async function updateLeague(
  id: string,
  input: {
    name?: string;
    description?: string | null;
    total_rounds?: number;
    default_vibe_mode?: boolean;
    submission_window_hours?: number;
    voting_window_hours?: number;
  },
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

/** Get the caller's own per-league participation (vibe) setting. */
export async function getMyMembership(leagueId: string): Promise<Membership> {
  const res = await authenticatedRequest(`/api/v1/leagues/${leagueId}/membership`);
  if (!res.ok) {
    throw new ApiError(res.status, await readErrorMessage(res));
  }
  return (await res.json()) as Membership;
}

/** Remove a member from a league (organizer only). Resolves on 204. */
export async function removeMember(leagueId: string, userId: string): Promise<void> {
  const res = await authenticatedRequest(`/api/v1/leagues/${leagueId}/members/${userId}`, {
    method: "DELETE",
  });
  if (!res.ok) {
    throw new ApiError(res.status, await readErrorMessage(res));
  }
}

/** Promote or demote a member to/from co-organizer (MYS-99). Callable by any
 *  current admin (the fixed organizer or another co-organizer) on another
 *  active member. The backend 409s if targeting the fixed `organizer_id` user
 *  (that role isn't toggleable). Returns the updated LeagueMember. */
export async function updateMemberRole(
  leagueId: string,
  userId: string,
  role: "admin" | "member",
): Promise<LeagueMember> {
  const res = await authenticatedRequest(`/api/v1/leagues/${leagueId}/members/${userId}/role`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ role }),
  });
  if (!res.ok) {
    throw new ApiError(res.status, await readErrorMessage(res));
  }
  return (await res.json()) as LeagueMember;
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

/** Delete a league (organizer only). Resolves on 204. The backend returns 409
 *  when the league is in progress; the calm detail message ("cannot delete a
 *  league that is in progress") is surfaced on the thrown ApiError. */
export async function deleteLeague(leagueId: string): Promise<void> {
  const res = await authenticatedRequest(`/api/v1/leagues/${leagueId}`, {
    method: "DELETE",
  });
  if (!res.ok) {
    throw new ApiError(res.status, await readErrorMessage(res));
  }
}

/** Validate an invite token and return a public league preview. Works for
 *  anyone with the link — authenticatedRequest attaches a bearer token when
 *  one is present (so the backend can compute `already_member`) but never
 *  requires one; the endpoint accepts anonymous callers too (MYS-181). */
export async function getInvitePreview(token: string): Promise<InvitePreview> {
  const res = await authenticatedRequest(`/api/v1/invites/${encodeURIComponent(token)}`);
  if (!res.ok) {
    throw new ApiError(res.status, await readErrorMessage(res));
  }
  return (await res.json()) as InvitePreview;
}

/** Join a league via invite token. Returns the joined League on 200. */
export async function acceptInvite(token: string): Promise<League> {
  const res = await authenticatedRequest(`/api/v1/invites/${encodeURIComponent(token)}/accept`, {
    method: "POST",
  });
  if (!res.ok) {
    throw new ApiError(res.status, await readErrorMessage(res));
  }
  return (await res.json()) as League;
}

// --------------------------------------------------------------------------- //
// Song search & resolution (MYS-44 / MYS-17). Search is powered by Deezer
// (keyless); selecting a result resolves its URL via Odesli.
// --------------------------------------------------------------------------- //

/** Streaming platforms the app surfaces, matching the backend's normalized keys. */
export type PlatformKey = "spotify" | "youtube" | "youtubeMusic" | "deezer" | "appleMusic";

/** A canonical, platform-agnostic song resolved from a link or a search pick.
 *  `platforms` only contains the platforms that actually have a link. */
export type ResolvedSong = {
  title: string;
  artist: string | null;
  album: string | null;
  thumbnail_url: string | null;
  isrc: string | null;
  platforms: Partial<Record<PlatformKey, string>>;
};

/** A single search hit (GET /api/v1/songs/search). `resolve_url` is the platform
 *  URL handed back to POST /api/v1/songs/resolve when the user picks this track. */
export type SongSearchTrack = {
  id: string;
  title: string;
  artist: string | null;
  album: string | null;
  thumbnail_url: string | null;
  isrc: string | null;
  resolve_url: string | null;
};

/** Search response: up to 10 tracks, plus a flag asking the user to add an
 *  artist when the title alone was too ambiguous. */
export type SongSearchResults = {
  results: SongSearchTrack[];
  too_many_results: boolean;
};

/** Resolve input: either a pasted platform URL, or a known song identity from a
 *  search result (skips the URL-identification step on the server). */
export type ResolveInput =
  | { url: string }
  | {
      title: string;
      artist?: string | null;
      isrc?: string | null;
      album?: string | null;
      thumbnail_url?: string | null;
    };

/** Resolve a song to its cross-service platform links. Pass a pasted link
 *  (`{ url }`) or a picked search result's identity. */
export async function resolveSong(input: ResolveInput): Promise<ResolvedSong> {
  const res = await authenticatedRequest("/api/v1/songs/resolve", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
  if (!res.ok) {
    throw new ApiError(res.status, await readErrorMessage(res));
  }
  return (await res.json()) as ResolvedSong;
}

/** Search Deezer by title, optionally narrowed by artist. */
export async function searchSongs(q: string, artist?: string): Promise<SongSearchResults> {
  const params = new URLSearchParams({ q });
  if (artist && artist.trim()) {
    params.set("artist", artist.trim());
  }
  const res = await authenticatedRequest(`/api/v1/songs/search?${params.toString()}`);
  if (!res.ok) {
    throw new ApiError(res.status, await readErrorMessage(res));
  }
  return (await res.json()) as SongSearchResults;
}

// --------------------------------------------------------------------------- //
// Rounds, submissions & playlist (MYS-18 / MYS-51 / MYS-53).
// --------------------------------------------------------------------------- //

/** A round's lifecycle state. `pending` rounds are pre-created and not yet open. */
export type RoundState = "pending" | "open_submission" | "open_voting" | "closed";

/** A round within a league. `theme` is null until the organizer names the round
 *  (rounds are auto-created as `pending` with no theme at league creation). */
export type Round = {
  id: string;
  league_id: string;
  round_number: number;
  theme: string | null;
  state: RoundState;
  description: string | null;
  submission_deadline: string | null;
  voting_deadline: string | null;
  votes_per_player: number;
  created_at: string;
  closed_at: string | null;
  /** Submission progress (MYS-101): songs in so far, out of the league's active
   *  members. Shown as "X of Y submitted" while submissions are open. */
  submission_count: number;
  member_count: number;
  /** Whether the current viewer has submitted / voted in this round. Used for
   *  confirmation indicators on the league-home round tile. */
  viewer_submitted: boolean;
  viewer_voted: boolean;
  /** Voting progress (MYS-110): distinct voters and eligible voters (playing
   *  submitters). Shown as "X of Y voted" while voting is open. */
  voted_count: number;
  voting_eligible_count: number;
};

/** A song submitted to a round (GET .../submissions, .../submissions/mine). */
export type SubmissionResult = {
  id: string;
  round_id: string;
  user_id: string;
  isrc: string;
  title: string;
  artist: string;
  album: string | null;
  album_art_url: string | null;
  note: string | null;
  participation_mode: string;
  created_at: string;
  league_previously_submitted: boolean;
};

/** One entry in a round's voting playlist. Anonymous for everyone but the
 *  caller: `is_own` is true for the viewer's own submission (which they can't
 *  vote for), and never reveals any other submitter. */
export type PlaylistEntry = {
  submission_id: string;
  isrc: string;
  title: string;
  artist: string;
  album: string | null;
  album_art_url: string | null;
  // participation_mode is intentionally absent (MYS-112): vibing is private, so
  // the voting playlist never reveals which songs are vibers'.
  platforms: Partial<Record<PlatformKey, string>>;
  preferred_url: string | null;
  is_own: boolean;
  /** The submitter's optional context note, shown to all voters (MYS-150). */
  submitter_note: string | null;
};

/** A round's voting playlist (GET /rounds/:id/playlist). `youtube_playlist_url`
 *  is a ready-to-open `watch_videos?video_ids=...` link for the whole mix, or
 *  null when no track resolved to YouTube; `youtube_track_count` is how many
 *  tracks made it into that link (0 when null). */
export type Playlist = {
  round_id: string;
  round_number: number;
  theme: string | null;
  state: RoundState;
  entries: PlaylistEntry[];
  youtube_playlist_url: string | null;
  youtube_track_count: number;
  /** Voting progress (MYS-102): "X of Y voted or noted · Z just vibing".
   *  `voting_eligible` = playing participants (eligible voters), `voting_acted`
   *  = those who've voted or left a note, `vibing_count` = vibing participants. */
  voting_eligible: number;
  voting_acted: number;
  vibing_count: number;
};

/** Create a round in a league (organizer only). */
export async function createRound(
  leagueId: string,
  input: {
    theme: string;
    description?: string | null;
    votes_per_player?: number;
    submission_deadline?: string | null;
    voting_deadline?: string | null;
  },
): Promise<Round> {
  const res = await authenticatedRequest(`/api/v1/leagues/${leagueId}/rounds`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
  if (!res.ok) {
    throw new ApiError(res.status, await readErrorMessage(res));
  }
  return (await res.json()) as Round;
}

/** Get all rounds for a league (members). */
export async function getRounds(leagueId: string): Promise<Round[]> {
  const res = await authenticatedRequest(`/api/v1/leagues/${leagueId}/rounds`);
  if (!res.ok) {
    throw new ApiError(res.status, await readErrorMessage(res));
  }
  return (await res.json()) as Round[];
}

/** Get a single round (members). */
export async function getRound(roundId: string): Promise<Round> {
  const res = await authenticatedRequest(`/api/v1/rounds/${roundId}`);
  if (!res.ok) {
    throw new ApiError(res.status, await readErrorMessage(res));
  }
  return (await res.json()) as Round;
}

/** Update a round — edit fields or advance its state (organizer only). */
export async function updateRound(
  roundId: string,
  input: {
    theme?: string | null;
    description?: string | null;
    state?: RoundState;
    submission_deadline?: string | null;
    voting_deadline?: string | null;
  },
): Promise<Round> {
  const res = await authenticatedRequest(`/api/v1/rounds/${roundId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
  if (!res.ok) {
    throw new ApiError(res.status, await readErrorMessage(res));
  }
  return (await res.json()) as Round;
}

/** Push a round's voting deadline to an organizer-chosen time, up to 48h past
 *  the current deadline (organizer only, MYS-180). `votingDeadline` is an ISO
 *  datetime string. Only valid while the round is still open_voting. */
export async function extendVotingDeadline(
  roundId: string,
  votingDeadline: string,
): Promise<Round> {
  const res = await authenticatedRequest(`/api/v1/rounds/${roundId}/extend-voting`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ voting_deadline: votingDeadline }),
  });
  if (!res.ok) {
    throw new ApiError(res.status, await readErrorMessage(res));
  }
  return (await res.json()) as Round;
}

/** The fields needed to add or replace a submitted song. Shared by submitSong
 *  (add) and editSubmission (replace one). `participation_mode` is a per-player
 *  round stance the backend keeps uniform across all your songs (MYS-116). */
export type SubmissionInput = {
  title: string;
  artist: string;
  isrc: string;
  album?: string | null;
  album_art_url?: string | null;
  note?: string | null;
  participation_mode?: "playing" | "vibing";
};

/** Add a song to a round (MYS-116). Round must be open_submission; the backend
 *  returns 409 once you've reached the league's songs-per-submission cap. */
export async function submitSong(
  roundId: string,
  input: SubmissionInput,
): Promise<SubmissionResult> {
  const res = await authenticatedRequest(`/api/v1/rounds/${roundId}/submissions`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
  if (!res.ok) {
    throw new ApiError(res.status, await readErrorMessage(res));
  }
  return (await res.json()) as SubmissionResult;
}

/** Replace one of your songs in a round wholesale (MYS-116). Setting
 *  `participation_mode` updates the stance across all your songs (uniform). */
export async function editSubmission(
  roundId: string,
  submissionId: string,
  input: SubmissionInput,
): Promise<SubmissionResult> {
  const res = await authenticatedRequest(`/api/v1/rounds/${roundId}/submissions/${submissionId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
  if (!res.ok) {
    throw new ApiError(res.status, await readErrorMessage(res));
  }
  return (await res.json()) as SubmissionResult;
}

/** Update only the submitter note on an existing submission without replacing the
 *  track (MYS-150). The round must still be open_submission. Pass null to clear. */
export async function updateSubmissionNote(
  roundId: string,
  submissionId: string,
  note: string | null,
): Promise<SubmissionResult> {
  const res = await authenticatedRequest(
    `/api/v1/rounds/${roundId}/submissions/${submissionId}/note`,
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ note }),
    },
  );
  if (!res.ok) {
    throw new ApiError(res.status, await readErrorMessage(res));
  }
  return (await res.json()) as SubmissionResult;
}

/** Remove one of your songs from a round (MYS-116). Resolves on 204. */
export async function deleteSubmission(roundId: string, submissionId: string): Promise<void> {
  const res = await authenticatedRequest(`/api/v1/rounds/${roundId}/submissions/${submissionId}`, {
    method: "DELETE",
  });
  if (!res.ok) {
    throw new ApiError(res.status, await readErrorMessage(res));
  }
}

/** Get your songs for a round (MYS-116) — a list of up to the league's cap,
 *  oldest first. Empty when you haven't submitted yet. */
export async function getMySubmissions(roundId: string): Promise<SubmissionResult[]> {
  const res = await authenticatedRequest(`/api/v1/rounds/${roundId}/submissions/mine`);
  if (!res.ok) {
    throw new ApiError(res.status, await readErrorMessage(res));
  }
  return (await res.json()) as SubmissionResult[];
}

/** Get a round's anonymous voting playlist (available once voting opens). */
export async function getPlaylist(roundId: string): Promise<Playlist> {
  const res = await authenticatedRequest(`/api/v1/rounds/${roundId}/playlist`);
  if (!res.ok) {
    throw new ApiError(res.status, await readErrorMessage(res));
  }
  return (await res.json()) as Playlist;
}

// --- Spotify playlist generation (MYS-83, MYS-169) ----------------------- //

/** Whether the server has Spotify configured at all, and whether the shared
 *  MysteryMixClub playlist account is connected (MYS-169) — not the calling
 *  user's own connection; no member connects their own account anymore. */
export type SpotifyStatus = {
  configured: boolean;
  connected: boolean;
};

/** Is Spotify configured, and is the shared playlist account connected? */
export async function getSpotifyStatus(): Promise<SpotifyStatus> {
  const res = await authenticatedRequest("/api/v1/spotify/status");
  if (!res.ok) {
    throw new ApiError(res.status, await readErrorMessage(res));
  }
  return (await res.json()) as SpotifyStatus;
}

/** Begin the connect flow: returns the Spotify consent URL to redirect to.
 *  `returnTo` is an in-app path (e.g. the current round) the callback lands on
 *  after consent, so the user comes back where they started.
 *
 *  Dormant (MYS-169): no round-page UI calls this anymore now that playlist
 *  generation runs off one shared account. Kept for ops to (re)connect that
 *  shared account, and in case per-user OAuth is ever revived. */
export async function connectSpotify(returnTo?: string): Promise<{ authorize_url: string }> {
  const path = returnTo
    ? `/api/v1/spotify/connect?return_to=${encodeURIComponent(returnTo)}`
    : "/api/v1/spotify/connect";
  const res = await authenticatedRequest(path);
  if (!res.ok) {
    throw new ApiError(res.status, await readErrorMessage(res));
  }
  return (await res.json()) as { authorize_url: string };
}

/** Read-only: the round's existing Spotify playlist link, or null if
 *  generation hasn't run (or hasn't matched anything) yet (MYS-169, MYS-176).
 *  Generation is automatic, triggered on the voting_open transition — this
 *  never triggers it itself. */
export async function getSpotifyPlaylistLink(
  roundId: string,
): Promise<{ playlist_url: string | null }> {
  const res = await authenticatedRequest(`/api/v1/rounds/${roundId}/spotify-playlist`);
  if (!res.ok) {
    throw new ApiError(res.status, await readErrorMessage(res));
  }
  return (await res.json()) as { playlist_url: string | null };
}

/** Get all submissions for a round (revealed only after it closes). */
export async function getRoundSubmissions(roundId: string): Promise<SubmissionResult[]> {
  const res = await authenticatedRequest(`/api/v1/rounds/${roundId}/submissions`);
  if (!res.ok) {
    throw new ApiError(res.status, await readErrorMessage(res));
  }
  return (await res.json()) as SubmissionResult[];
}

// --------------------------------------------------------------------------- //
// Round results / reveal (MYS-23 / MYS-24). Available only once a round is
// closed (GET /rounds/:id/results → 409 while still open).
// --------------------------------------------------------------------------- //

/** A note shown in the reveal — body + author, no edit affordances. */
export type ResultNote = {
  body: string;
  author_display_name: string;
  created_at: string;
};

/** A voter identified on the closed-round reveal (MYS-173). Voting stays
 *  anonymous through open_voting; this only ever appears once a round is
 *  closed. */
export type ResultVoter = {
  user_id: string;
  display_name: string;
};

/** A revealed submission: submitter named, vote total, and the notes it drew. */
export type ResultSubmission = {
  submission_id: string;
  user_id: string;
  submitter_display_name: string;
  isrc: string;
  title: string;
  artist: string;
  album: string | null;
  album_art_url: string | null;
  // participation_mode is intentionally absent (MYS-112): the reveal never shows
  // who vibed.
  /** Playback links so the reveal tiles are playable. */
  platforms: Partial<Record<PlatformKey, string>>;
  submitter_note: string | null;
  vote_count: number;
  notes: ResultNote[];
  /** Who voted for this song (MYS-173), name-sorted. Absent from the vibe-safe
   *  WinnerReveal/RevealPick shapes by design — a vibing viewer never sees
   *  voter identity, matching the existing no-vote-count rule (MYS-112). */
  voters: ResultVoter[];
};

/** One ranked player on the leaderboard — every submitter competes, vibers
 *  included (MYS-112). */
export type LeaderboardEntry = {
  user_id: string;
  display_name: string;
  vote_count: number;
  rank: number;
};

/** A submission that drew the most notes this round (ties yield several). */
export type MostNotedWinner = {
  submission_id: string;
  title: string;
  artist: string;
  note_count: number;
  notes: ResultNote[];
};

/** The vibe-safe winner shape shown to a vibing viewer (MYS-112): named, no
 *  vote count. */
export type WinnerReveal = {
  submission_id: string;
  title: string;
  artist: string;
  submitter_display_name: string;
};

/** A vibe-safe pick shown to a vibing viewer (MYS-134): a submitted song with
 *  submitter + notes, but no vote count. */
export type RevealPick = {
  submission_id: string;
  submitter_display_name: string;
  title: string;
  artist: string;
  /** Playback links so the tiles are playable. */
  platforms: Partial<Record<PlatformKey, string>>;
  submitter_note: string | null;
  notes: ResultNote[];
};

/** A closed round's reveal (GET /rounds/:id/results). The reveal is gated by the
 *  viewer's participation mode (MYS-112): a player gets the full reveal
 *  (`submissions` + `leaderboard`); a viber (`viewer_is_vibing`) gets only
 *  `winners` + `picks` + `most_noted`, with `submissions`/`leaderboard` empty so
 *  no vote counts or rankings leak. `picks` is the unscored tracklist a viber
 *  sees (MYS-134). `most_noted.winners` is empty when the round drew no notes. */
export type RoundResults = {
  round_id: string;
  round_number: number;
  theme: string | null;
  state: RoundState;
  viewer_is_vibing: boolean;
  submissions: ResultSubmission[];
  leaderboard: LeaderboardEntry[];
  most_noted: { note_count: number; winners: MostNotedWinner[] };
  winners: WinnerReveal[];
  picks: RevealPick[];
};

/** Get a closed round's reveal results. Backend returns 409 while the round is
 *  still open, surfaced here as an ApiError. */
export async function getResults(roundId: string): Promise<RoundResults> {
  const res = await authenticatedRequest(`/api/v1/rounds/${roundId}/results`);
  if (!res.ok) {
    throw new ApiError(res.status, await readErrorMessage(res));
  }
  return (await res.json()) as RoundResults;
}

// --------------------------------------------------------------------------- //
// Votes (MYS-20).
// --------------------------------------------------------------------------- //

/** The caller's votes for a round (POST/GET .../votes). `submission_ids` is the
 *  full set the caller has cast; `count` mirrors its length. */
export type Votes = {
  round_id: string;
  submission_ids: string[];
  count: number;
  votes_per_player: number;
};

/** One entry in the vote counts tally — shows the song and how many votes it has,
 *  but NOT who voted or any notes (notes revealed only at round close). */
export type VoteCountEntry = {
  submission_id: string;
  title: string;
  artist: string;
  vote_count: number;
};

/** Vote counts for all songs in a round (GET .../vote-counts). Shows the running
 *  tally during voting. The caller can see how many votes each song has, but
 *  notes remain hidden until the round closes. */
export type VoteCounts = {
  round_id: string;
  entries: VoteCountEntry[];
};

/** Replace the caller's votes for a round with `submissionIds` (idempotent).
 *  Round must be open_voting. Backend rejects an empty set (409). */
export async function castVotes(roundId: string, submissionIds: string[]): Promise<Votes> {
  const res = await authenticatedRequest(`/api/v1/rounds/${roundId}/votes`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ submission_ids: submissionIds }),
  });
  if (!res.ok) {
    throw new ApiError(res.status, await readErrorMessage(res));
  }
  return (await res.json()) as Votes;
}

/** Get the caller's current votes for a round (empty when nothing is cast). */
export async function getMyVotes(roundId: string): Promise<Votes> {
  const res = await authenticatedRequest(`/api/v1/rounds/${roundId}/votes/mine`);
  if (!res.ok) {
    throw new ApiError(res.status, await readErrorMessage(res));
  }
  return (await res.json()) as Votes;
}

/** Get vote counts for all songs in a round. Shows running tally during voting
 *  without revealing notes (notes appear only after round closes). */
export async function getVoteCounts(roundId: string): Promise<VoteCounts> {
  const res = await authenticatedRequest(`/api/v1/rounds/${roundId}/vote-counts`);
  if (!res.ok) {
    throw new ApiError(res.status, await readErrorMessage(res));
  }
  return (await res.json()) as VoteCounts;
}

// --------------------------------------------------------------------------- //
// Notes (MYS-21).
// --------------------------------------------------------------------------- //

/** A note left on a submission during voting (POST/GET .../notes). Allowed only
 *  while the round is open_voting; eligible on any song (playing or vibing). */
export type Note = {
  id: string;
  submission_id: string;
  round_id: string;
  author_id: string;
  author_display_name: string;
  body: string;
  created_at: string;
};

/** Leave a note on a submission (body 1–280 chars). Round must be open_voting
 *  (backend returns 409 otherwise). Returns the created Note. */
export async function addNote(submissionId: string, body: string): Promise<Note> {
  const res = await authenticatedRequest(`/api/v1/submissions/${submissionId}/notes`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ body }),
  });
  if (!res.ok) {
    throw new ApiError(res.status, await readErrorMessage(res));
  }
  return (await res.json()) as Note;
}

/** Get the notes left on a submission, ordered oldest-first. */
export async function getNotes(submissionId: string): Promise<Note[]> {
  const res = await authenticatedRequest(`/api/v1/submissions/${submissionId}/notes`);
  if (!res.ok) {
    throw new ApiError(res.status, await readErrorMessage(res));
  }
  return (await res.json()) as Note[];
}

// --------------------------------------------------------------------------- //
// Platform admin (MYS-128). Every endpoint here is platform-admin-only; the
// backend returns 403 for non-admins. The UI gates the whole page on
// `is_platform_admin` from /users/me so these are never called by others.
// --------------------------------------------------------------------------- //

/** A user as surfaced in the admin search results (GET /api/v1/admin/users). */
export type AdminUser = {
  id: string;
  email: string;
  display_name: string;
  created_at: string;
};

/** Search users by an email substring (platform-admin only). */
export async function adminSearchUsers(email: string): Promise<AdminUser[]> {
  const res = await authenticatedRequest(`/api/v1/admin/users?email=${encodeURIComponent(email)}`);
  if (!res.ok) {
    throw new ApiError(res.status, await readErrorMessage(res));
  }
  return (await res.json()) as AdminUser[];
}

/** Hard-delete a user and all their data (platform-admin only). Resolves on 204.
 *  The backend returns 409 on a self-delete; that detail surfaces on the error. */
export async function adminDeleteUser(userId: string): Promise<void> {
  const res = await authenticatedRequest(`/api/v1/admin/users/${userId}`, {
    method: "DELETE",
  });
  if (!res.ok) {
    throw new ApiError(res.status, await readErrorMessage(res));
  }
}

/** Generate a platform invite (MYS-182, platform-admin only): grants signup
 *  only, no league attachment. Same shareable-link shape as a league invite. */
export async function adminCreateInvite(): Promise<Invite> {
  const res = await authenticatedRequest("/api/v1/admin/invites", {
    method: "POST",
  });
  if (!res.ok) {
    throw new ApiError(res.status, await readErrorMessage(res));
  }
  return (await res.json()) as Invite;
}

export { ApiError };
