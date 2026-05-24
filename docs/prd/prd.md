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
Submits songs, votes on other players' submissions, receives scores, appears on the leaderboard.

### Player (Just Vibing mode)
Submits songs, does not vote, does not receive scores, is visible to the group as "Just Vibing." Eligible for Most Noted. Can be permanent (profile setting) or per-round.

---

## 4. User Stories

### Onboarding & League Setup

- As an **Organizer**, I can create a new league with a name and description, so that my friend group has a home for our music rounds.
- As an **Organizer**, I can generate a shareable invite link, so that friends can join without requiring a platform account.
- As an **Organizer**, I can set the number of votes each player gets per round, so that I can tune the competitive dynamic for my group.
- As a **Player**, I can join a league via an invite link without needing a Spotify account or any specific streaming service, so that platform preference is never a barrier.
- As a **Player**, I can set my preferred streaming service once in my profile, so that playlist links always open in my app of choice.
- As a **Player**, I can choose Just Vibing as my default participation mode in my profile, so that I never have to opt out round by round.

### Round Flow

- As an **Organizer**, I can create a new round with a theme and submission deadline, so that players know what to submit and when.
- As a **Player**, I can submit a song by pasting a link from any streaming service, so that I can share music from wherever I already listen.
- As a **Player**, I can submit a song by searching natively within MysteryMixClub, so that I don't need to leave the app to find a track.
- As a **Player**, I can add an optional note to my submission explaining why I chose this song, so that my submission has context and humanity.
- As a **Player**, I can listen to the round playlist in my preferred streaming service once submissions close, so that I never have to use a service I don't want to.
- As a **Player (Playing)**, I can vote for my favorite submissions after listening, so that scoring reflects genuine engagement with the music.
- As a **Player (Just Vibing)**, I am prompted to leave a written note instead of a vote, so that I can still express appreciation without participating in scoring.
- As a **Player**, I can see round results including scores, vote breakdowns, and who submitted what after voting closes, so that the reveal is a shared moment.

### Just Vibing

- As a **Player**, I can opt into Just Vibing mode for a single round without changing my permanent participation setting, so that I can honor emotionally difficult rounds without leaving the league.
- As a **Player (Just Vibing)**, my submission is visually equal to all other submissions in the playlist, so that I never feel like a second-class participant.
- As a **Player (Just Vibing)**, I can see that other players left notes on my song even though I didn't receive votes, so that I feel seen and appreciated.
- As a **Player (Playing)**, when I would normally vote for a Just Vibing player's song, I am prompted to leave a written note instead, so that the appreciation mechanic works naturally without breaking the voting flow.

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

**Playing (default)**
- Full submission, voting, and scoring
- Appears on leaderboard
- Can vote for any Playing player's submission
- Cannot vote for Just Vibing players' submissions — prompted to leave a note instead

**Just Vibing**
- Full song submission, equal weight in playlist
- No voting, no scores received
- Visible to group with warm, inclusive language ("Just Vibing this round" / "Vibing")
- Available as permanent profile setting or per-round opt-in
- Per-round opt-in available until submission deadline
- Can return to Playing mode any subsequent round with zero friction
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
- Just Vibing players do not appear on the leaderboard

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
- Default participation mode (Playing / Just Vibing)
- Round history (leagues and participation — visible to self only by default)
- Account deletion — full data removal, no residual records

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
| Leaderboard scope | Product | Per-round only, or cumulative season? Both? |
| Ad provider | Product | Must vet for political content policy before launch |

---

*Next document: `technical-design.md`*
