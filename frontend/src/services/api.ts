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
  const res = await authenticatedRequest(`/api/v1/leagues/${leagueId}/members/${userId}`, {
    method: "DELETE",
  });
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
export type PlatformKey = "spotify" | "youtube" | "deezer" | "appleMusic";

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
  participation_mode: string;
  platforms: Partial<Record<PlatformKey, string>>;
  preferred_url: string | null;
  is_own: boolean;
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

/** Submit (or replace) your song for a round. Round must be open_submission. */
export async function submitSong(
  roundId: string,
  input: {
    title: string;
    artist: string;
    isrc: string;
    album?: string | null;
    album_art_url?: string | null;
    note?: string | null;
    participation_mode?: "playing" | "vibing";
  },
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

/** Get your submission for a round, or null if you haven't submitted yet. */
export async function getMySubmission(roundId: string): Promise<SubmissionResult | null> {
  const res = await authenticatedRequest(`/api/v1/rounds/${roundId}/submissions/mine`);
  if (res.status === 404) return null;
  if (!res.ok) {
    throw new ApiError(res.status, await readErrorMessage(res));
  }
  return (await res.json()) as SubmissionResult;
}

/** Get a round's anonymous voting playlist (available once voting opens). */
export async function getPlaylist(roundId: string): Promise<Playlist> {
  const res = await authenticatedRequest(`/api/v1/rounds/${roundId}/playlist`);
  if (!res.ok) {
    throw new ApiError(res.status, await readErrorMessage(res));
  }
  return (await res.json()) as Playlist;
}

// --- Spotify playlist generation (MYS-83) -------------------------------- //

/** Whether the server has Spotify configured at all, and whether the current
 *  user has connected their Spotify account. */
export type SpotifyStatus = {
  configured: boolean;
  connected: boolean;
};

/** A track we couldn't match to Spotify when building the playlist. */
export type SpotifyUnmatchedTrack = {
  submission_id: string;
  title: string;
  artist: string;
};

/** Result of creating a round's Spotify playlist. `playlist_url` is null when
 *  no track matched (no empty playlist is created); `track_count` of
 *  `total_count` were added, and `unmatched` lists what couldn't be placed. */
export type SpotifyPlaylistResult = {
  round_id: string;
  playlist_url: string | null;
  track_count: number;
  total_count: number;
  unmatched: SpotifyUnmatchedTrack[];
};

/** Is Spotify configured/connected for the current user? */
export async function getSpotifyStatus(): Promise<SpotifyStatus> {
  const res = await authenticatedRequest("/api/v1/spotify/status");
  if (!res.ok) {
    throw new ApiError(res.status, await readErrorMessage(res));
  }
  return (await res.json()) as SpotifyStatus;
}

/** Begin the connect flow: returns the Spotify consent URL to redirect to.
 *  `returnTo` is an in-app path (e.g. the current round) the callback lands on
 *  after consent, so the user comes back where they started. */
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

/** Create a saved Spotify playlist for the round in the user's library. */
export async function createSpotifyPlaylist(roundId: string): Promise<SpotifyPlaylistResult> {
  const res = await authenticatedRequest(`/api/v1/rounds/${roundId}/spotify-playlist`, {
    method: "POST",
  });
  if (!res.ok) {
    throw new ApiError(res.status, await readErrorMessage(res));
  }
  return (await res.json()) as SpotifyPlaylistResult;
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
  participation_mode: string;
  submitter_note: string | null;
  vote_count: number;
  notes: ResultNote[];
};

/** One ranked, Playing-only player on the leaderboard (vibing excluded). */
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

/** A closed round's full results (GET /rounds/:id/results). `most_noted.winners`
 *  is empty when the round drew no notes. */
export type RoundResults = {
  round_id: string;
  round_number: number;
  theme: string | null;
  state: RoundState;
  submissions: ResultSubmission[];
  leaderboard: LeaderboardEntry[];
  most_noted: { note_count: number; winners: MostNotedWinner[] };
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

export { ApiError };
