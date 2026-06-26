# MysteryMixClub — Product Requirements Document

**Document type:** PRD  
**Status:** Draft v1.0  
**Phase:** PDLC — Definition  
**Depends on:** `discovery/problem-statement.md`, `discovery/personas.md`, `discovery/competitive-analysis.md`

---

## 1. Purpose & Scope

This document defines the requirements for MysteryMixClub v1 — an invite-only, platform-agnostic music league for close-knit friend groups. It is the authoritative specification for the MVP build.

**In scope:** Everything required to run a complete music league round, across multiple streaming platforms, with inclusive participation modes.

**Out of scope:** See Section 7.

---

## 2. Product Principles

These principles are non-negotiable. Every feature, design decision, and technical choice must be evaluated against them.

### 1. Platform-Agnostic by Conviction

MysteryMixClub is not Spotify-optional — it is genuinely platform-neutral. No player should ever have to compromise their values, their wallet, or their listening habits to participate. This is not a feature. It is the foundation.

> *Technical implication: song identity is always stored as a canonical ISRC, never as a platform-specific URI. Platform resolution happens at playback time, not at submission time.*

### 2. Inclusion is a Design Constraint

Every feature must be evaluated against one question: would this keep the Outsider in the room? If a design decision makes participation conditional on competitive appetite, it is wrong.

### 3. Privacy by Architecture

User data is never collected for AI training, advertising targeting, or third-party sharing. Taste profiles are opt-in only. The right to be forgotten is absolute and technically enforced — not just a policy. There will never be an opt-out AI feature.

### 4. Resonance Over Consensus

The product celebrates music that moves people, not just music that wins votes. Most Noted exists alongside scoring because emotional response is as valid as taste alignment.

### 5. The Community Owns the Experience

Round themes are crowd-sourced. The league belongs to everyone in it, not just the organizer. Features that distribute ownership are prioritized over features that centralize control.

> *Note: Crowd-sourced themes are a fast follow, not MVP. This principle is stated now so it shapes v1 architecture — the data model should anticipate it.*

---

## 3. Users & Roles

### League Organizer
Creates and manages the league. Sets round themes (in v1), manages invites, advances rounds. Has all player permissions plus admin controls.

### Player (Playing mode)
Submits a song, votes on the round's (anonymous) submissions, receives scores, appears on the leaderboard.

### Player (Just Vibing mode)
Submits a song that **competes like any other** — votable and eligible to win — but **does not cast votes**; they listen and may leave notes. Vibing is **private**: no one else can tell a submission came from a viber. Set as a **per-league** default (seeded from the league's default at join, changeable anytime) with a **per-round override**. At reveal a viber sees the winner(s), Most Noted, and notes — but **not** the leaderboard or vote counts. Eligible for Most Noted.

> **Decision — Just Vibing v2 (2026-06-26, MYS-112).** This reverses the original model (a *visible, non-competitive* opt-out that received no votes and was excluded from the leaderboard). Vibing is now a *private voting opt-out*: the viber's song still competes, nobody sees who vibed, and the only differences are that the viber doesn't cast votes and sees a results view limited to winner + Most Noted + notes. The §2.2 inclusion principle still holds — its expression shifts from "celebrated and seen" to "invisible and equal."

---

## 4. User Stories

### Onboarding & League Setup

- As an **Organizer**, I can create a new league with a name and description, so that my friend group has a home for our music rounds.
- As an **Organizer**, I can generate a shareable invite link, so that friends can join without requiring a platform account.
- As an **Organizer**, I can set the number of votes each player gets per round, so that I can tune the competitive dynamic for my group.
- As an **Organizer**, I can set the league's default participation mode (Playing / Just Vibing) at creation, so that new members inherit the vibe I want for the group.
- As a **Player**, I can join a league via an invite link without needing a Spotify account or any specific streaming service, so that platform preference is never a barrier.
- As a **Player**, I can set my preferred streaming service once in my profile, so that playlist links always open in my app of choice.
- As a **Player**, I can set my Just Vibing default for a league (seeded from the league default, changeable anytime), so that I never have to opt out round by round.

### Round Flow

- As an **Organizer**, I can create a new round with a theme and submission deadline, so that players know what to submit and when.
- As a **Player**, I can submit a song by pasting a link from any streaming service, so that I can share music from wherever I already listen.
- As a **Player**, I can submit a song by searching natively within MysteryMixClub, so that I don't need to leave the app to find a track.
- As a **Player**, I can add an optional note to my submission explaining why I chose this song, so that my submission has context and humanity.
- As a **Player**, I can listen to the round playlist in my preferred streaming service once submissions close, so that I never have to use a service I don't want to.
- As a **Player (Playing)**, I can vote for my favorite submissions after listening, so that scoring reflects genuine engagement with the music.
- As a **Player (Just Vibing)**, I can leave notes on the songs I enjoy even though I don't cast votes, so that I can still express appreciation.
- As a **Player (Playing)**, I can see full round results — scores, vote breakdowns, leaderboard, and who submitted what — after voting closes, so that the reveal is a shared moment.

### Just Vibing

- As a **Player**, I can opt into Just Vibing for a single round without changing my per-league setting, so that I can honor emotionally difficult rounds without leaving the league.
- As a **Player (Just Vibing)**, my submission is **indistinguishable** from every other in the playlist — no one can tell I'm vibing — so that I never feel like a second-class participant.
- As a **Player (Just Vibing)**, my song still competes and can win, so that opting out of voting doesn't mean opting out of the game.
- As a **Player (Just Vibing)**, I can see the notes left on my song at reveal, so that I feel appreciated even though I don't see the vote counts.
- As a **Player (Just Vibing)**, my reveal shows the winner(s), Most Noted, and notes but not the leaderboard or vote counts, so that my round stays about resonance rather than ranking.

### Most Noted

- As **any Player**, my song is eligible for Most Noted regardless of whether I am Playing or Just Vibing, so that resonance is recognized across all participation modes.
- As **any Player**, I can see which song received the Most Noted recognition at the end of a round alongside the scoring results, so that it feels like a genuine parallel celebration.
- As **any Player**, I can read the notes left on the Most Noted song, so that I understand why it resonated with people.

### Invites

- As an **Organizer**, I can share an invite link that allows new players to join the league, so that the group can grow organically.
- As a **Player**, I can share the same invite link with a friend, so that bringing someone new in doesn't require organizer involvement every time.

### Monetization

- As a **Player**, I can use the full app for free, so that cost is never a barrier to participation.
- As a **Player**, I can leave a tip to support the app, so that I can contribute if I love it.
- Banner ads are displayed non-intrusively — no audio, no interruptions, no political content — so that the experience is never compromised by the monetization layer.

---

## 5. Features

### 5.1 Song Submission

**Native Search**
- Powered by Odesli/Songlink API
- Returns canonical track with ISRC identifier
- Search results show song title, artist, album art
- Platform-neutral — results are not tied to any streaming service

**Link Paste**
- Accepts links from any supported streaming service (Spotify, YouTube, Deezer, Apple Music, and others)
- Resolves via Odesli to canonical ISRC track
- Confirmation screen shows resolved track before submission is confirmed
- Both paths produce identical canonical track records in the database

**Submission Record**
Each submission stores:
- ISRC code (canonical identifier)
- Song title, artist, album, album art (from Odesli metadata)
- Optional note from submitter (plain text, reasonable character limit TBD)
- Submitter ID
- Timestamp
- Participation mode at time of submission (Playing / Just Vibing)

### 5.2 Multi-Platform Playback

**Supported platforms at launch:** Spotify, YouTube, Deezer

**Mechanism:**
- Odesli universal links resolve each ISRC to platform-specific URLs at playback time
- Player's preferred service (set in profile) determines which link is surfaced by default
- All platform options always visible as a fallback
- YouTube link always available as a universal fallback for tracks unavailable on a player's chosen service

**Round Playlist**
- Generated at submission deadline close
- Submissions are anonymous and shuffled (identity revealed after voting closes)
- Accessible from the round page as a single "Listen" action

### 5.3 Participation Modes

> **Decision — Just Vibing v2 (2026-06-26, MYS-112).** Vibing is a *private voting opt-out*, not a non-competitive one. A viber's song competes and can win; the viber simply doesn't cast votes, and nobody can tell who vibed. See the callout in §3 for what changed from the original model.

Modes are set per-league (a league default, seeded onto each member at join and changeable anytime) with a per-round override ("Just Vibes for this Round"). Precedence: round override → per-league member setting → league default.

**Playing (default)**
- Full submission, voting, and scoring
- Appears on the leaderboard
- Votes on the round's anonymous submissions — every song is votable (vibers' included; you can't tell which are theirs), except your own

**Just Vibing**
- Full song submission — **competes equally**, votable, eligible to win on votes
- Does **not** cast votes; may leave notes
- **Private** — no badge or label exposes a viber to anyone, during voting or at reveal
- Per-round override available until the submission deadline; per-league default changeable anytime
- Can return to Playing any subsequent round with zero friction
- Reveal is limited to winner(s) + Most Noted + notes (no leaderboard, no vote counts)
- Eligible for Most Noted

### 5.4 Most Noted

- Tracks written notes left on each submission across a round
- Awarded to the song with the most notes at round close
- Eligible to all submissions regardless of participation mode
- Displayed alongside (not instead of) scoring results at round reveal
- Notes on the winning song are surfaced publicly at reveal
- In the event of a tie, both songs are recognized

### 5.5 Voting & Scoring

- Organizer sets number of votes per player at league creation (default: 3)
- Votes are blind during the voting period — no vote counts visible until reveal
- Submissions are anonymous during voting — submitter revealed at round close
- Scores accumulate across rounds on a league leaderboard
- All submitters compete, including Just Vibing players — a viber's song can place on the leaderboard and win (they simply don't cast votes themselves)
- The reveal is gated by the viewer's mode for the round: Playing sees the full reveal (leaderboard, vote counts, all picks); Just Vibing sees only winner(s) + Most Noted + notes

### 5.6 Round Management

- Organizer creates round with: theme, submission deadline, voting deadline
- Organizer can manually close submission or voting periods early
- Round states: Open for Submission → Open for Voting → Closed / Results
- Players receive notifications at key state transitions (submission open, voting open, results revealed)

### 5.7 Invites

- Organizer generates a shareable invite link at league creation
- Invite link can be reshared by any existing league member
- Joining via invite link creates an account and adds player to the league in one flow
- No streaming service account required to join

### 5.8 User Profile

- Display name
- Preferred streaming service (used for playback link defaults)
- Round history (leagues and participation — visible to self only by default)
- Account deletion — full data removal, no residual records

> Participation mode is **per-league**, not a profile-wide setting (see §5.3) — it lives on league membership, with a per-round override. There is no account-level default participation mode.

### 5.9 Monetization

- Non-intrusive banner ads (no audio, no interruptions, no political content)
- Tip jar — visible, low-friction, optional
- No features gated behind payment in v1

---

## 6. Technical Notes for Build

These are product-level technical constraints, not implementation decisions. The technical design document will expand on these.

- **Song identity:** Always ISRC. Never store a Spotify URI, YouTube ID, or Deezer track ID as the primary identifier. Platform IDs are derived at playback time via Odesli.
- **Odesli/Songlink API:** Primary dependency for both search and link resolution. Rate limits and fallback behavior must be accounted for.
- **Platform support is additive:** Adding a new streaming service should require no schema changes — only a new platform resolver. Design for this from day one.
- **Privacy architecture:** No analytics pipelines that store individual user behavior by default. Aggregate-only metrics at launch. Individual taste profiles are a future opt-in feature — do not build the data collection layer until that feature is scoped.
- **Right to be forgotten:** Account deletion must cascade to all associated data — submissions, votes, notes, participation records. No soft deletes for personal data.

---

## 7. Out of Scope for MVP

These are explicitly deferred. They are not forgotten — they belong in the fast follow backlog.

| Feature | Rationale |
|---------|-----------|
| Crowd-sourced round themes | Core loop must work first; this enhances it |
| Additional streaming platforms (Tidal, Apple Music, etc.) | Odesli supports them — add after validating core flow |
| Taste profiles & analytics | Opt-in, privacy-sensitive; needs separate scoping |
| Export / copy playlist (CSV, clipboard) | Nice-to-have; Odesli universal links cover the core need |
| Native mobile apps | Web-first, mobile-responsive for v1 |
| Public leagues / open registration | Invite-only for v1; validate with real users first |
| Custom scoring rules | Default voting model covers v1 needs |
| Round theme voting | Fast follow after crowd-sourcing is scoped |
| AI features of any kind | Opt-in only, never opt-out; not in v1 |

---

## 8. Open Questions

These need resolution before or during build:

| Question | Owner | Notes |
|----------|-------|-------|
| Character limit for submission notes | Product | Suggest 280 chars — long enough to say something, short enough to stay human |
| Notification delivery method | Technical | Email for v1? Push notifications fast follow? |
| Odesli rate limits | Technical | Free tier limits need validation against expected usage |
| Tie-breaking for Most Noted | Product | Current spec: both songs recognized. Confirm. |
| Leaderboard scope | Product | Per-league |
| Ad provider | Product | Must vet for political content policy before launch |

---

*Next document: `technical-design.md`*
