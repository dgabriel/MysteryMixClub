# MysteryMixClub — End-to-End Manual Test Plan

**Document type:** QA / Test Plan
**Test style:** Manual, point-and-click (human tester)
**Scope:** Multiple players across multiple devices, run concurrently

---

## 1. Objective & Scope

Validate the full club lifecycle — auth → club creation → invites → mystery mix
submission → voting → reveal — as a human clicking through the real UI, across
**multiple players on multiple devices** simultaneously. Staging environment
(DO Droplet), not prod.

In scope: all wired routes (`/login`, `/auth/verify`, `/onboarding`, `/home`,
`/clubs/new`, `/clubs/:id`, `/mixes/:id`, `/join/:token`).

Out of scope: load/perf, automated tests, prod deploy gate.

---

## 2. Environment & Fixtures

| Item | Value |
|------|-------|
| URL | staging (DO Droplet `67.207.81.183` / staging host) |
| Email delivery | Resend — each player needs a **real, accessible inbox** to click the magic link (15-min expiry, single-use). Rate limit: **max 5 magic-link requests per email per hour.** |
| Reset | Use fresh emails per run, or have DB access to clear `users`/clubs between runs. |

**Players & devices** (run concurrently — keep all sessions live):

| Player | Role | Device / browser |
|--------|------|------------------|
| A | Organizer | Desktop Chrome |
| B | Member | Android phone (Chrome) |
| C | Member | iPhone (Safari) |
| D | Member / removed | Desktop Firefox or second laptop |

---

## 3. Preconditions

- All four inboxes reachable on their respective devices.
- Clear browser state for each player (no leftover session).
- Spotify/YouTube installed on B and C to test playlist platform links opening.

---

## 4. Test Scenarios

### A. Auth & Onboarding (per player, all devices)

| # | Step | Expected |
|---|------|----------|
| A1 | Visit base URL | Redirects to `/login` |
| A2 | Enter email, submit | "Check email" screen shown |
| A3 | Open inbox **on that device**, click magic link | Lands `/auth/verify`, verifies, → `/onboarding` (first login) |
| A4 | Enter display name, submit | → `/home` (My Clubs) |
| A5 | Request a 2nd link, click the **first/old** link | Rejected (single-use/expired) — clear error, not silent |
| A6 | Request 6 links within an hour | 6th is rate-limited |
| A7 | Returning login (existing user) | Skips onboarding → straight to `/home` |

### B. Club Creation & Management — Player A (organizer)

| # | Step | Expected |
|---|------|----------|
| B1 | `/home` → create club | `/clubs/new` form |
| B2 | Submit name + description + total_mixes (e.g. 4) | → club home `/clubs/:id`; header "mix 0 of 4"; A listed as **organizer** badge |
| B3 | Tap **edit** → change name, description, total_mixes → save | Values update in place |
| B4 | Set total_mixes below current_mix / to 0 or blank | Rejected / no-op (min 1 enforced) |
| B5 | Confirm **edit** and **remove member** controls visible only to A | Hidden for B/C/D |

### C. Invites & Joining (multi-player, multi-device)

| # | Step | Expected |
|---|------|----------|
| C1 | A taps **invite** → generates link → **copy** | "copied" confirmation; share link field populated |
| C2 | A on mobile: **share** button present (Web Share API); desktop hides it | Correct per-device |
| C3 | Send link to B, C, D | — |
| C4 | B (logged in) opens `/join/:token` | Club preview shown; join → B in members list |
| C5 | C **logged out** opens invite link | Bounces to login, preserves `pendingInvitePath`; after magic-link auth + onboarding, lands back on join → joins |
| C6 | A's screen: refresh club home | Members count reflects B & C |
| C7 | A removes D after D joins | D removed from list; D loses access to club on refresh |
| C8 | Open an expired/garbage `/join/:token` | Clear "invalid invite" state, no crash |

### D. Mystery Mix — Submission phase

| # | Step | Expected |
|---|------|----------|
| D1 | A → **new mystery mix**, theme e.g. "late summer feels" → create | Mystery mix appears, badge **submissions open**; club current_mix advances |
| D2 | Each player opens mystery mix `/mixes/:id` | State-aware submission UI; only A sees **open voting** organizer control |
| D3 | B searches a song (Odesli) and submits | "your submission" card with title/artist + mode badge |
| D4 | B taps **change song**, submits a different track | Replaces prior submission (one per player) |
| D5 | C submits via search on Safari/iOS | Works; touch targets adequate |
| D6 | Search a track Odesli can't resolve / missing ISRC | Clear error ("missing an ID and can't be submitted"), not silent |
| D7 | Player who hasn't submitted | Sees empty submit card, no leakage of others' picks |

### E. Voting phase (concurrent, multi-device)

| # | Step | Expected |
|---|------|----------|
| E1 | A taps **open voting** | Mystery mix badge → **voting open** for all players |
| E2 | All players open the mystery mix | Anonymous, **shuffled** playlist — no submitter names; order may differ per player |
| E3 | Select votes | Counter "N / 3 selected"; cannot exceed `votes_per_player` (extra cards disabled) |
| E4 | Toggle a vote off/on | Selection + counter update |
| E5 | **Cast votes** | "votes saved" confirmation |
| E6 | Reload page | Saved votes re-seeded as selected |
| E7 | Two players vote at the same time | Each sees only their own selection; no cross-contamination |
| E8 | Tap a platform link (Spotify/YouTube) on B/C | Opens correct track in new tab/app |
| E9 | Confirm a player cannot vote for / count their own selection improperly | Self-vote behavior matches backend rule (verify) |

### F. Notes (during voting)

| # | Step | Expected |
|---|------|----------|
| F1 | Expand **notes** on a song | Lazily loads, shows count |
| F2 | **leave a note**, type toward 280 chars | Live N/280 counter; blocks past 280; empty disabled |
| F3 | Submit note | Appears with author display name; count increments |
| F4 | Another player opens same song's notes | Sees F3's note |
| F5 | Cancel a composing note | Draft cleared, no post |

### G. Reveal / Results (closed)

| # | Step | Expected |
|---|------|----------|
| G1 | A taps **close mystery mix** | Badge → **closed** for all |
| G2 | All players open the mystery mix | Reveal view: **Most Noted** (Rust accent — should be the ONLY Rust on screen), **Leaderboard** (ranked, no Rust), **the picks** with submitters now revealed |
| G3 | Own pick | Labeled "you" |
| G4 | Vote counts & ranking | Match votes cast in E |
| G5 | Notes from F | Shown read-only under each pick / Most Noted |
| G6 | Tie in Most Noted | All winners co-recognized |
| G7 | Complete the final mystery mix (reach total_mixes) | Club badge flips to **complete** (Rust); "new mystery mix" hidden |

### H. Cross-device & Session

| # | Step | Expected |
|---|------|----------|
| H1 | Player logged in on two devices simultaneously | Both work independently |
| H2 | Leave a session idle past access-token expiry (60 min), then act | Silent refresh; no forced re-login |
| H3 | Log out | Session invalidated; protected routes bounce to `/login` |
| H4 | "Log out of all devices" (if surfaced) | All sessions for that user 401 on next action |

### I. Tenant Isolation (security — MYS-48)

| # | Step | Expected |
|---|------|----------|
| I1 | Player B, while not a member of A's *other* club, opens its `/clubs/:id` URL directly | Denied / not-found, no data leak |
| I2 | Removed player D opens club/mystery-mix URL after removal | Access denied |
| I3 | Open another club's `/mixes/:id` directly | Denied |

### J. PWA / Responsive

| # | Step | Expected |
|---|------|----------|
| J1 | B/C: "Add to Home Screen" (onboarding instructions for iOS + Android) | Installs; launches standalone |
| J2 | Launch installed PWA offline | Shell loads; data actions show connection-needed error, not blank crash |
| J3 | Rotate / various widths | Layout responsive; tap targets fine; inputs are underline-style (no border boxes) |

### K. Negative / Edge

| # | Step | Expected |
|---|------|----------|
| K1 | Submit a song after voting opens | Blocked |
| K2 | Cast votes after mystery mix closed | Blocked |
| K3 | Non-organizer hits organizer actions via URL/API | Forbidden |
| K4 | Empty theme / empty display name / whitespace-only | Validation blocks |
| K5 | Note / submission with HTML or emoji | Sanitized, renders safely (XSS check) |

---

## 5. Known Gaps to Flag (not yet testable by click)

- **No "just vibing" UI** — `participation_mode` only comes from
  `users.default_vibe_mode`, which nothing in the UI sets (onboarding captures
  display name only; there is no profile/settings screen). The vibing-participant
  voting/reveal paths (sit-out, "just vibing" badges) exist in code but are
  unreachable by click. To test E/G vibing branches, seed `default_vibe_mode=true`
  in the DB for one player, or expose a toggle.
- **No profile/settings screen** in the route map — `preferred_service` (which
  platform link is surfaced first) and account deletion (`DELETE /users/me`) have
  no UI to exercise.

---

## 6. Exit Criteria

- All A–K scenarios pass on all four players/devices, OR failures logged with
  issue + screenshot.
- No tenant-isolation leak (Section I) — blocker if any fail.
- Reveal scores/ranking match votes cast.
