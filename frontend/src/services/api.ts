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
 * carry it into the verify link to auto-join the club. The dev verify link the
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
  // auto-joined to that club. Absent invite → plain verify (existing users).
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
 *  the user organizes an active club. */
export async function deleteAccount(): Promise<void> {
  const res = await authenticatedRequest("/api/v1/users/me", { method: "DELETE" });
  if (!res.ok) {
    throw new ApiError(res.status, await readErrorMessage(res));
  }
}

/** Fetch a JSON dump of the caller's own data (right of access / portability,
 *  MYS-185): profile, submissions, votes, notes, club memberships. Returns
 *  the raw parsed object — the caller decides what to do with it (e.g. trigger
 *  a file download), so this isn't typed beyond "some JSON object". */
export async function exportMyData(): Promise<Record<string, unknown>> {
  const res = await authenticatedRequest("/api/v1/users/me/export");
  if (!res.ok) {
    throw new ApiError(res.status, await readErrorMessage(res));
  }
  return (await res.json()) as Record<string, unknown>;
}

/** A club as returned by the backend (GET/POST /api/v1/clubs). */
export type Club = {
  id: string;
  name: string;
  description: string | null;
  organizer_id: string;
  total_mixes: number;
  votes_per_player: number;
  /** How many songs a player may submit per mix (MYS-116). Fixed at club
   *  setup; 1 = classic one-song behaviour, max 5. */
  songs_per_submission: number;
  current_mix: number;
  state: string;
  /** Admin-set default participation mode for the club (MYS-112). A member's
   *  own setting lives on their membership (getMyMembership), not here. */
  default_vibe_mode: boolean;
  /** Hour-granular deadline windows stamped onto each mix when it opens
   *  (MYS-158/160). Bounds: 4–168 hours (1 week). */
  submission_window_hours: number;
  voting_window_hours: number;
  created_at: string;
  completed_at: string | null;
};

/** The caller's own per-club participation setting (GET/PATCH
 *  /clubs/:id/membership). Vibing is private — this is only ever the caller's
 *  own setting, never another member's. */
export type Membership = {
  club_id: string;
  user_id: string;
  vibe_mode: boolean;
};

/** A member of a club (GET /api/v1/clubs/:id/members). `is_admin` is true
 *  for the fixed organizer or anyone holding the co-organizer `"admin"` role
 *  (MYS-99). */
export type ClubMember = {
  user_id: string;
  display_name: string;
  joined_at: string;
  is_organizer: boolean;
  is_admin: boolean;
};

/** An invite (POST /api/v1/clubs/:id/invites, or POST /api/v1/admin/invites
 *  for a platform invite). ``club_id`` is null for a platform invite
 *  (MYS-182): grants signup only, no club attachment. */
export type Invite = {
  id: string;
  club_id: string | null;
  token: string;
  created_by: string;
  created_at: string;
  expires_at: string | null;
};

/** Public preview of an invite shown before joining (GET /api/v1/invites/:token).
 *  ``club_id``/``club_name``/``member_count`` are null for a platform
 *  invite (MYS-182) — there's no club to preview, just a signup grant. */
export type InvitePreview = {
  club_id: string | null;
  club_name: string | null;
  member_count: number | null;
  /** True when the viewer is already an active member of this club — the
   *  caller should redirect straight in rather than showing the join screen,
   *  most relevant on an otherwise-expired link (MYS-181). Always false for
   *  a platform invite. */
  already_member: boolean;
};

/** Create a new club. Returns the created Club on 201. Only the provided
 *  fields are serialized; JSON.stringify drops undefined optional keys. */
export async function createClub(input: {
  name: string;
  total_mixes: number;
  votes_per_player?: number;
  songs_per_submission?: number;
  description?: string;
  default_vibe_mode?: boolean;
  submission_window_hours?: number;
  voting_window_hours?: number;
}): Promise<Club> {
  const res = await authenticatedRequest("/api/v1/clubs", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
  if (!res.ok) {
    throw new ApiError(res.status, await readErrorMessage(res));
  }
  return (await res.json()) as Club;
}

/** Get all clubs for the current user. */
export async function getClubs(): Promise<Club[]> {
  const res = await authenticatedRequest("/api/v1/clubs");
  if (!res.ok) {
    throw new ApiError(res.status, await readErrorMessage(res));
  }
  return (await res.json()) as Club[];
}

/** Get a single club by id. */
export async function getClub(id: string): Promise<Club> {
  const res = await authenticatedRequest(`/api/v1/clubs/${id}`);
  if (!res.ok) {
    throw new ApiError(res.status, await readErrorMessage(res));
  }
  return (await res.json()) as Club;
}

/** Get the members of a club. */
export async function getClubMembers(id: string): Promise<ClubMember[]> {
  const res = await authenticatedRequest(`/api/v1/clubs/${id}/members`);
  if (!res.ok) {
    throw new ApiError(res.status, await readErrorMessage(res));
  }
  return (await res.json()) as ClubMember[];
}

/** All-time vote leaderboard for a club (MYS-157): ranked members by total
 *  votes received across all closed mixes, with 0-vote members included. */
export async function getClubLeaderboard(id: string): Promise<LeaderboardEntry[]> {
  const res = await authenticatedRequest(`/api/v1/clubs/${id}/leaderboard`);
  if (!res.ok) {
    throw new ApiError(res.status, await readErrorMessage(res));
  }
  return (await res.json()) as LeaderboardEntry[];
}

/** Update a club (organizer only). An explicit null description is sent as-is;
 *  only undefined keys are dropped by JSON.stringify. Returns the updated Club. */
export async function updateClub(
  id: string,
  input: {
    name?: string;
    description?: string | null;
    total_mixes?: number;
    default_vibe_mode?: boolean;
    submission_window_hours?: number;
    voting_window_hours?: number;
  },
): Promise<Club> {
  const res = await authenticatedRequest(`/api/v1/clubs/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
  if (!res.ok) {
    throw new ApiError(res.status, await readErrorMessage(res));
  }
  return (await res.json()) as Club;
}

/** Get the caller's own per-club participation (vibe) setting. */
export async function getMyMembership(clubId: string): Promise<Membership> {
  const res = await authenticatedRequest(`/api/v1/clubs/${clubId}/membership`);
  if (!res.ok) {
    throw new ApiError(res.status, await readErrorMessage(res));
  }
  return (await res.json()) as Membership;
}

/** Remove a member from a club (organizer only). Resolves on 204. */
export async function removeMember(clubId: string, userId: string): Promise<void> {
  const res = await authenticatedRequest(`/api/v1/clubs/${clubId}/members/${userId}`, {
    method: "DELETE",
  });
  if (!res.ok) {
    throw new ApiError(res.status, await readErrorMessage(res));
  }
}

/** Promote or demote a member to/from co-organizer (MYS-99). Callable by any
 *  current admin (the fixed organizer or another co-organizer) on another
 *  active member. The backend 409s if targeting the fixed `organizer_id` user
 *  (that role isn't toggleable). Returns the updated ClubMember. */
export async function updateMemberRole(
  clubId: string,
  userId: string,
  role: "admin" | "member",
): Promise<ClubMember> {
  const res = await authenticatedRequest(`/api/v1/clubs/${clubId}/members/${userId}/role`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ role }),
  });
  if (!res.ok) {
    throw new ApiError(res.status, await readErrorMessage(res));
  }
  return (await res.json()) as ClubMember;
}

/** Generate an invite link for a club (organizer or member). Returns the Invite. */
export async function createInvite(clubId: string): Promise<Invite> {
  const res = await authenticatedRequest(`/api/v1/clubs/${clubId}/invites`, {
    method: "POST",
  });
  if (!res.ok) {
    throw new ApiError(res.status, await readErrorMessage(res));
  }
  return (await res.json()) as Invite;
}

/** Delete a club (organizer only). Resolves on 204. The backend returns 409
 *  when the club is in progress; the calm detail message ("cannot delete a
 *  club that is in progress") is surfaced on the thrown ApiError. */
export async function deleteClub(clubId: string): Promise<void> {
  const res = await authenticatedRequest(`/api/v1/clubs/${clubId}`, {
    method: "DELETE",
  });
  if (!res.ok) {
    throw new ApiError(res.status, await readErrorMessage(res));
  }
}

/** Validate an invite token and return a public club preview. Works for
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

/** Join a club via invite token. Returns the joined Club on 200. */
export async function acceptInvite(token: string): Promise<Club> {
  const res = await authenticatedRequest(`/api/v1/invites/${encodeURIComponent(token)}/accept`, {
    method: "POST",
  });
  if (!res.ok) {
    throw new ApiError(res.status, await readErrorMessage(res));
  }
  return (await res.json()) as Club;
}

// --------------------------------------------------------------------------- //
// Song search & resolution (MYS-44 / MYS-17). Search is powered by Deezer
// (keyless); selecting a result resolves its URL via Odesli.
// --------------------------------------------------------------------------- //

/** Streaming platforms the app surfaces, matching the backend's normalized keys. */
export type PlatformKey =
  | "spotify"
  | "youtube"
  | "youtubeMusic"
  | "deezer"
  | "appleMusic"
  | "bandcamp";

/** A canonical, platform-agnostic song resolved from a link or a search pick.
 *  `platforms` only contains the platforms that actually have a link. */
export type ResolvedSong = {
  title: string;
  artist: string | null;
  album: string | null;
  thumbnail_url: string | null;
  isrc: string | null;
  /** Set only for a source-only track (a Bandcamp/YouTube pick with no catalog
   *  ISRC, MYS-201); null for a normal catalog track. `source_key` is the exact
   *  identity (`youtube:<id>` / `bandcamp:<artist>/<slug>`) submitted in place of
   *  an isrc; `source_url` is the reconstructed page link. */
  source: "youtube" | "bandcamp" | null;
  source_key: string | null;
  source_url: string | null;
  /** Bandcamp's numeric track id, echoed back on submit for the embedded player
   *  (MYS-204); null for everything else. */
  bandcamp_track_id: string | null;
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
 *  search result (skips the URL-identification step on the server).
 *
 *  `allow_source_only` opts into source-only matches (MYS-201): off (default), a
 *  Bandcamp/YouTube link with no catalog ISRC still 404s exactly as before; on,
 *  it resolves to a source-only ResolvedSong (null isrc, `source`/`source_key`
 *  set). Only the paste flow ever sets it, and only as a retry after the default
 *  resolve misses. */
export type ResolveInput =
  | { url: string; allow_source_only?: boolean }
  | {
      title: string;
      artist?: string | null;
      isrc?: string | null;
      album?: string | null;
      thumbnail_url?: string | null;
      allow_source_only?: boolean;
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
// Mixes, submissions & playlist (MYS-18 / MYS-51 / MYS-53).
// --------------------------------------------------------------------------- //

/** A mix's lifecycle state. `pending` mixes are pre-created and not yet open. */
export type MixState = "pending" | "open_submission" | "open_voting" | "closed";

/** A mix within a club. `theme` is null until the organizer names the mix
 *  (mixes are auto-created as `pending` with no theme at club creation). */
export type Mix = {
  id: string;
  club_id: string;
  mix_number: number;
  theme: string | null;
  state: MixState;
  description: string | null;
  submission_deadline: string | null;
  voting_deadline: string | null;
  votes_per_player: number;
  created_at: string;
  closed_at: string | null;
  /** Submission progress (MYS-101): songs in so far, out of the club's active
   *  members. Shown as "X of Y submitted" while submissions are open. */
  submission_count: number;
  member_count: number;
  /** Whether the current viewer has submitted / voted in this mix. Used for
   *  confirmation indicators on the club-home mix tile. */
  viewer_submitted: boolean;
  viewer_voted: boolean;
  /** Voting progress (MYS-110): distinct voters and eligible voters (playing
   *  submitters). Shown as "X of Y voted" while voting is open. */
  voted_count: number;
  voting_eligible_count: number;
};

/** A song submitted to a mix (GET .../submissions, .../submissions/mine). */
export type SubmissionResult = {
  id: string;
  mix_id: string;
  user_id: string;
  /** Null for a source-only track (MYS-201) — `source`/`source_url` identify it
   *  instead. */
  isrc: string | null;
  source: "youtube" | "bandcamp" | null;
  source_url: string | null;
  title: string;
  artist: string;
  album: string | null;
  album_art_url: string | null;
  note: string | null;
  participation_mode: string;
  created_at: string;
  club_previously_submitted: boolean;
};

/** One entry in a mix's voting playlist. Anonymous for everyone but the
 *  caller: `is_own` is true for the viewer's own submission (which they can't
 *  vote for), and never reveals any other submitter. */
export type PlaylistEntry = {
  submission_id: string;
  isrc: string | null;
  /** Set for a source-only track (Bandcamp/YouTube, no catalog ISRC — MYS-201):
   *  `source` drives the "BANDCAMP ONLY"/"YOUTUBE ONLY" badge, `source_url` is
   *  the exact page link. Null for a normal catalog track. */
  source: "youtube" | "bandcamp" | null;
  source_url: string | null;
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

/** A mix's voting playlist (GET /mixes/:id/playlist). `youtube_playlist_url`
 *  is a ready-to-open `watch_videos?video_ids=...` link for the whole mix, or
 *  null when no track resolved to YouTube; `youtube_track_count` is how many
 *  tracks made it into that link (0 when null). */
export type Playlist = {
  mix_id: string;
  mix_number: number;
  theme: string | null;
  state: MixState;
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

/** Create a mix in a club (organizer only). */
export async function createMix(
  clubId: string,
  input: {
    theme: string;
    description?: string | null;
    votes_per_player?: number;
    submission_deadline?: string | null;
    voting_deadline?: string | null;
  },
): Promise<Mix> {
  const res = await authenticatedRequest(`/api/v1/clubs/${clubId}/mixes`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
  if (!res.ok) {
    throw new ApiError(res.status, await readErrorMessage(res));
  }
  return (await res.json()) as Mix;
}

/** Get all mixes for a club (members). */
export async function getMixes(clubId: string): Promise<Mix[]> {
  const res = await authenticatedRequest(`/api/v1/clubs/${clubId}/mixes`);
  if (!res.ok) {
    throw new ApiError(res.status, await readErrorMessage(res));
  }
  return (await res.json()) as Mix[];
}

/** Get a single mix (members). */
export async function getMix(mixId: string): Promise<Mix> {
  const res = await authenticatedRequest(`/api/v1/mixes/${mixId}`);
  if (!res.ok) {
    throw new ApiError(res.status, await readErrorMessage(res));
  }
  return (await res.json()) as Mix;
}

/** Update a mix — edit fields or advance its state (organizer only). */
export async function updateMix(
  mixId: string,
  input: {
    theme?: string | null;
    description?: string | null;
    state?: MixState;
    submission_deadline?: string | null;
    voting_deadline?: string | null;
  },
): Promise<Mix> {
  const res = await authenticatedRequest(`/api/v1/mixes/${mixId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
  if (!res.ok) {
    throw new ApiError(res.status, await readErrorMessage(res));
  }
  return (await res.json()) as Mix;
}

/** Push a mix's voting deadline to an organizer-chosen time, up to 48h past
 *  the current deadline (organizer only, MYS-180). `votingDeadline` is an ISO
 *  datetime string. Only valid while the mix is still open_voting. */
export async function extendVotingDeadline(
  mixId: string,
  votingDeadline: string,
): Promise<Mix> {
  const res = await authenticatedRequest(`/api/v1/mixes/${mixId}/extend-voting`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ voting_deadline: votingDeadline }),
  });
  if (!res.ok) {
    throw new ApiError(res.status, await readErrorMessage(res));
  }
  return (await res.json()) as Mix;
}

/** The fields needed to add or replace a submitted song. Shared by submitSong
 *  (add) and editSubmission (replace one). `participation_mode` is a per-player
 *  mix stance the backend keeps uniform across all your songs (MYS-116). */
export type SubmissionInput = {
  title: string;
  artist: string;
  /** Exactly one of `isrc` / `source_key` identifies the track (MYS-201): isrc
   *  for a catalog track, source_key (`youtube:<id>` / `bandcamp:<artist>/<slug>`)
   *  for a source-only Bandcamp/YouTube pick. The backend rejects both/neither. */
  isrc?: string | null;
  source_key?: string | null;
  /** Bandcamp's numeric track id from the resolve step, echoed back for the
   *  embedded player (MYS-204); omitted for everything else. */
  bandcamp_track_id?: string | null;
  album?: string | null;
  album_art_url?: string | null;
  note?: string | null;
  participation_mode?: "playing" | "vibing";
};

/** Add a song to a mix (MYS-116). Mix must be open_submission; the backend
 *  returns 409 once you've reached the club's songs-per-submission cap. */
export async function submitSong(
  mixId: string,
  input: SubmissionInput,
): Promise<SubmissionResult> {
  const res = await authenticatedRequest(`/api/v1/mixes/${mixId}/submissions`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
  if (!res.ok) {
    throw new ApiError(res.status, await readErrorMessage(res));
  }
  return (await res.json()) as SubmissionResult;
}

/** Replace one of your songs in a mix wholesale (MYS-116). Setting
 *  `participation_mode` updates the stance across all your songs (uniform). */
export async function editSubmission(
  mixId: string,
  submissionId: string,
  input: SubmissionInput,
): Promise<SubmissionResult> {
  const res = await authenticatedRequest(`/api/v1/mixes/${mixId}/submissions/${submissionId}`, {
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
 *  track (MYS-150). The mix must still be open_submission. Pass null to clear. */
export async function updateSubmissionNote(
  mixId: string,
  submissionId: string,
  note: string | null,
): Promise<SubmissionResult> {
  const res = await authenticatedRequest(
    `/api/v1/mixes/${mixId}/submissions/${submissionId}/note`,
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

/** Remove one of your songs from a mix (MYS-116). Resolves on 204. */
export async function deleteSubmission(mixId: string, submissionId: string): Promise<void> {
  const res = await authenticatedRequest(`/api/v1/mixes/${mixId}/submissions/${submissionId}`, {
    method: "DELETE",
  });
  if (!res.ok) {
    throw new ApiError(res.status, await readErrorMessage(res));
  }
}

/** Get your songs for a mix (MYS-116) — a list of up to the club's cap,
 *  oldest first. Empty when you haven't submitted yet. */
export async function getMySubmissions(mixId: string): Promise<SubmissionResult[]> {
  const res = await authenticatedRequest(`/api/v1/mixes/${mixId}/submissions/mine`);
  if (!res.ok) {
    throw new ApiError(res.status, await readErrorMessage(res));
  }
  return (await res.json()) as SubmissionResult[];
}

/** Get a mix's anonymous voting playlist (available once voting opens). */
export async function getPlaylist(mixId: string): Promise<Playlist> {
  const res = await authenticatedRequest(`/api/v1/mixes/${mixId}/playlist`);
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
 *  `returnTo` is an in-app path (e.g. the current mix) the callback lands on
 *  after consent, so the user comes back where they started.
 *
 *  Dormant (MYS-169): no mix-page UI calls this anymore now that playlist
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

/** Read-only: the mix's existing Spotify playlist link, or null if
 *  generation hasn't run (or hasn't matched anything) yet (MYS-169, MYS-176).
 *  Generation is automatic, triggered on the voting_open transition — this
 *  never triggers it itself. */
export async function getSpotifyPlaylistLink(
  mixId: string,
): Promise<{ playlist_url: string | null; unmatched: UnmatchedTrack[] }> {
  const res = await authenticatedRequest(`/api/v1/mixes/${mixId}/spotify-playlist`);
  if (!res.ok) {
    throw new ApiError(res.status, await readErrorMessage(res));
  }
  return (await res.json()) as { playlist_url: string | null; unmatched: UnmatchedTrack[] };
}

/** Why a mix submission didn't make an auto-generated playlist (MYS-201):
 *  `source_only` — a Bandcamp/YouTube track with no ISRC that can never match the
 *  service's catalog; `no_catalog_match` — a catalog track the service couldn't
 *  find. Drives the calm, informational gap summary near the playlist links. */
export type UnmatchedReason = "source_only" | "no_catalog_match";

export type UnmatchedTrack = {
  submission_id: string;
  title: string;
  artist: string;
  reason: UnmatchedReason;
  /** Set for a `source_only` track (Bandcamp/YouTube, no catalog ISRC — MYS-201):
   *  `source_url` links the exact page so the gap summary can offer it. Both null
   *  for a `no_catalog_match` track, which has nowhere to send the listener. */
  source: "youtube" | "bandcamp" | null;
  source_url: string | null;
};

export type ApplePlaylistResult = {
  /** Apple Music's Library, not the playlist itself — iOS can't deep-link to a
   *  library playlist (MYS-190). `playlist_name` is what locates it. */
  playlist_url: string;
  playlist_name: string;
  track_count: number;
  total_count: number;
  unmatched: UnmatchedTrack[];
};

/** The developer token MusicKit JS needs to run Apple's sign-in popup (MYS-108).
 *  Null when Apple Music isn't configured on this deployment — a normal state,
 *  in which the caller hides the Apple option entirely. */
export async function getAppleDeveloperToken(): Promise<{ token: string | null }> {
  const res = await authenticatedRequest("/api/v1/apple-music/developer-token");
  if (!res.ok) {
    throw new ApiError(res.status, await readErrorMessage(res));
  }
  return (await res.json()) as { token: string | null };
}

/** The caller's OWN Apple playlist link for a mix, or null (MYS-108).
 *  Apple library playlists can't be made public (MYS-107), so this is personal:
 *  it opens only for the user who generated it. */
export async function getApplePlaylistLink(
  mixId: string,
): Promise<{ playlist_url: string | null; playlist_name: string | null }> {
  const res = await authenticatedRequest(`/api/v1/mixes/${mixId}/apple-playlist`);
  if (!res.ok) {
    throw new ApiError(res.status, await readErrorMessage(res));
  }
  return (await res.json()) as { playlist_url: string | null; playlist_name: string | null };
}

/** Generate the mix's playlist in the caller's Apple Music library (MYS-108).
 *  Throws ApiError(401) when the Music User Token is expired/revoked — the
 *  caller should re-run the MusicKit popup rather than show a dead end. */
export async function createApplePlaylist(
  mixId: string,
  musicUserToken: string,
): Promise<ApplePlaylistResult> {
  // getTimezoneOffset() is minutes to add to LOCAL to get UTC — the server wants
  // the opposite, so negate it. Lets a rebuilt playlist's "[revised on HH:MM]"
  // read in the member's own clock rather than UTC.
  const tzOffsetMinutes = -new Date().getTimezoneOffset();
  const res = await authenticatedRequest(`/api/v1/mixes/${mixId}/apple-playlist`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      music_user_token: musicUserToken,
      tz_offset_minutes: tzOffsetMinutes,
    }),
  });
  if (!res.ok) {
    throw new ApiError(res.status, await readErrorMessage(res));
  }
  return (await res.json()) as ApplePlaylistResult;
}

/** Get all submissions for a mix (revealed only after it closes). */
export async function getMixSubmissions(mixId: string): Promise<SubmissionResult[]> {
  const res = await authenticatedRequest(`/api/v1/mixes/${mixId}/submissions`);
  if (!res.ok) {
    throw new ApiError(res.status, await readErrorMessage(res));
  }
  return (await res.json()) as SubmissionResult[];
}

// --------------------------------------------------------------------------- //
// Mix results / reveal (MYS-23 / MYS-24). Available only once a mix is
// closed (GET /mixes/:id/results → 409 while still open).
// --------------------------------------------------------------------------- //

/** A note shown in the reveal — body + author, no edit affordances. */
export type ResultNote = {
  body: string;
  author_display_name: string;
  created_at: string;
};

/** A voter identified on the closed-mix reveal (MYS-173). Voting stays
 *  anonymous through open_voting; this only ever appears once a mix is
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
  /** Null for a source-only track (MYS-201) — `source`/`source_url` identify it
   *  instead. */
  isrc: string | null;
  /** Set for a source-only track (Bandcamp/YouTube, no catalog ISRC — MYS-201):
   *  `source` drives the "BANDCAMP ONLY"/"YOUTUBE ONLY" badge, `source_url` is the
   *  exact page link. Null for a normal catalog track. */
  source: "youtube" | "bandcamp" | null;
  source_url: string | null;
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

/** A submission that drew the most notes this mix (ties yield several). */
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
  /** Set for a source-only track (Bandcamp/YouTube, no catalog ISRC — MYS-201):
   *  `source` drives the "BANDCAMP ONLY"/"YOUTUBE ONLY" badge, `source_url` is the
   *  exact page link. Null for a normal catalog track. */
  source: "youtube" | "bandcamp" | null;
  source_url: string | null;
  /** Playback links so the tiles are playable. */
  platforms: Partial<Record<PlatformKey, string>>;
  submitter_note: string | null;
  notes: ResultNote[];
};

/** A closed mix's reveal (GET /mixes/:id/results). The reveal is gated by the
 *  viewer's participation mode (MYS-112): a player gets the full reveal
 *  (`submissions` + `leaderboard`); a viber (`viewer_is_vibing`) gets only
 *  `winners` + `picks` + `most_noted`, with `submissions`/`leaderboard` empty so
 *  no vote counts or rankings leak. `picks` is the unscored tracklist a viber
 *  sees (MYS-134). `most_noted.winners` is empty when the mix drew no notes. */
export type MixResults = {
  mix_id: string;
  mix_number: number;
  theme: string | null;
  state: MixState;
  viewer_is_vibing: boolean;
  submissions: ResultSubmission[];
  leaderboard: LeaderboardEntry[];
  most_noted: { note_count: number; winners: MostNotedWinner[] };
  winners: WinnerReveal[];
  picks: RevealPick[];
};

/** Get a closed mix's reveal results. Backend returns 409 while the mix is
 *  still open, surfaced here as an ApiError. */
export async function getResults(mixId: string): Promise<MixResults> {
  const res = await authenticatedRequest(`/api/v1/mixes/${mixId}/results`);
  if (!res.ok) {
    throw new ApiError(res.status, await readErrorMessage(res));
  }
  return (await res.json()) as MixResults;
}

// --------------------------------------------------------------------------- //
// Votes (MYS-20).
// --------------------------------------------------------------------------- //

/** The caller's votes for a mix (POST/GET .../votes). `submission_ids` is the
 *  full set the caller has cast; `count` mirrors its length. */
export type Votes = {
  mix_id: string;
  submission_ids: string[];
  count: number;
  votes_per_player: number;
};

/** One entry in the vote counts tally — shows the song and how many votes it has,
 *  but NOT who voted or any notes (notes revealed only at mix close). */
export type VoteCountEntry = {
  submission_id: string;
  title: string;
  artist: string;
  vote_count: number;
};

/** Vote counts for all songs in a mix (GET .../vote-counts). Shows the running
 *  tally during voting. The caller can see how many votes each song has, but
 *  notes remain hidden until the mix closes. */
export type VoteCounts = {
  mix_id: string;
  entries: VoteCountEntry[];
};

/** Replace the caller's votes for a mix with `submissionIds` (idempotent).
 *  Mix must be open_voting. Backend rejects an empty set (409). */
export async function castVotes(mixId: string, submissionIds: string[]): Promise<Votes> {
  const res = await authenticatedRequest(`/api/v1/mixes/${mixId}/votes`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ submission_ids: submissionIds }),
  });
  if (!res.ok) {
    throw new ApiError(res.status, await readErrorMessage(res));
  }
  return (await res.json()) as Votes;
}

/** Get the caller's current votes for a mix (empty when nothing is cast). */
export async function getMyVotes(mixId: string): Promise<Votes> {
  const res = await authenticatedRequest(`/api/v1/mixes/${mixId}/votes/mine`);
  if (!res.ok) {
    throw new ApiError(res.status, await readErrorMessage(res));
  }
  return (await res.json()) as Votes;
}

/** Get vote counts for all songs in a mix. Shows running tally during voting
 *  without revealing notes (notes appear only after mix closes). */
export async function getVoteCounts(mixId: string): Promise<VoteCounts> {
  const res = await authenticatedRequest(`/api/v1/mixes/${mixId}/vote-counts`);
  if (!res.ok) {
    throw new ApiError(res.status, await readErrorMessage(res));
  }
  return (await res.json()) as VoteCounts;
}

// --------------------------------------------------------------------------- //
// Notes (MYS-21).
// --------------------------------------------------------------------------- //

/** A note left on a submission during voting (POST/GET .../notes). Allowed only
 *  while the mix is open_voting; eligible on any song (playing or vibing). */
export type Note = {
  id: string;
  submission_id: string;
  mix_id: string;
  author_id: string;
  author_display_name: string;
  body: string;
  created_at: string;
};

/** Leave a note on a submission (body 1–280 chars). Mix must be open_voting
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
 *  only, no club attachment. Same shareable-link shape as a club invite. */
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
