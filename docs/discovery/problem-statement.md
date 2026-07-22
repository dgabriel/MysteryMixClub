> Terminology: this document predates the July 2026 rename — "league" is now "club", "round" is now "mystery mix" (internal: mix).

# MysteryMixClub — Problem Statement

**Document type:** Discovery  
**Status:** Draft v1.0  
**Phase:** PDLC — Discovery

---

## The Problem

Music League pioneered collaborative music sharing among friend groups, but it has accumulated meaningful friction that pushes users away — particularly users who care deeply about music, community, and the ethics of the platforms they use.

There are three distinct pain points:

### 1. Vendor Lock-In

Music League requires Spotify. This excludes or alienates users who:

- Object to Spotify on ethical grounds (artist compensation, founder affiliations, ad content — including reported political ads mid-mix)
- Prefer alternative services such as Apple Music, Deezer, Tidal, or YouTube
- Experience catalog gaps where songs they want to share are unavailable on Spotify

The result: friends sit out, leagues fragment, and the shared experience breaks down at the platform layer before it even begins.

### 2. Scoring Feels Punishing for Some Players

Competitive scoring works well for some players and feels deeply wrong for others — sometimes simultaneously within the same league. Documented real-world cases include:

- **Emotional rounds** where voting felt disrespectful to the moment (e.g. rounds dedicated to grief or loss)
- **Taste outliers** who received consistently low scores and disengaged, feeling punished rather than celebrated for their perspective
- **Non-competitive players** who wanted to participate in the shared discovery experience but had no interest in judging or being judged

Music League offers no middle ground: you're either fully in the scoring system or you're out of the league entirely.

### 3. Intrusive Advertising

The free tier of Music League includes ads that disrupt the experience. For a user base that includes people who left Spotify specifically because of an unwanted ICE advertisement mid-mix, ad intrusiveness is not a minor UX issue — it is a values issue.

---

## The Opportunity

Build a platform-agnostic, emotionally inclusive music league experience that prioritizes connection and discovery over competition, without requiring everyone to play the same way.

---

## Target User

**Music connectors** — people for whom music is a primary language of care, memory, and shared identity. They make the road trip playlist. They text a song at midnight because it made them think of someone. They remember what was playing at important moments.

They are not trying to prove their taste is good. They want to share it, and they want their friends — all of them, regardless of platform preference or competitive appetite — in the same room.

**They value:**
- Shared discovery over personal validation
- Emotional resonance over chart performance
- Inclusion over competition
- Ethical alignment in the tools they use

---

## Proposed Solution Space

### Platform-Agnostic Playback

- Songs are submitted as canonical tracks, not platform-specific links
- Players submit via link (any service) or native search
- At round completion, each player chooses their preferred service for playback
- MysteryMixClub generates the playlist in their chosen format
- **MVP services:** Spotify, YouTube, Deezer
- **Fallback:** YouTube link always available for songs unavailable on a chosen service
- Adding new services is a defined future feature, not an MVP requirement

### Participation Modes

**Playing** — full submission, voting, and scoring. The default experience.

**Just Vibing** — for players who want to participate without the scoring layer.
- Full song submission (their contributions are equal and vital)
- No voting, no scores received
- Visible to the group with inclusive, non-stigmatizing language
- Available as a permanent profile setting or a per-round choice
- Per-round opt-in allows players to "just vibe this round" without permanently leaving the competitive tier
- Players in Just Vibing mode cannot receive votes from others; instead, other players are prompted to leave a written note

### Most Noted

A round-level recognition mechanic that runs parallel to — and independent of — scoring.

- Awarded to the song that received the most written notes in a round
- Eligible to **all songs**, regardless of whether the submitter is Playing or Just Vibing
- Rewards resonance and emotional response, not taste alignment
- Creates a second conversation anchor per round distinct from the leaderboard

### Monetization (v1)

- Free to play, always
- Non-intrusive banner ads only (no audio, no interruptions, no political content)
- Tip jar for users who want to support the app
- No freemium gates at launch; revisit if and when meaningful usage data exists

---

## Privacy Commitments

Privacy is a core product value, not a compliance checkbox. This matters especially for a user base that includes people who chose this platform partly on ethical grounds.

### User Privacy

- Players own their data — taste history, voting behavior, notes, and submissions
- **Right to be forgotten:** full account and data deletion on request, with no residual profiles or backups retained
- **Taste profiles are opt-in only** — players must actively choose to see their own taste analysis; nothing is collected or surfaced by default
- No data is sold, shared with third parties, or used for advertising targeting

### AI Features

- There will never be an opt-out AI feature — any AI-powered functionality will always require explicit, affirmative opt-in
- User data will never be used to train models, internally or externally
- Music metadata and artist content flowing through the platform will not be scraped, analyzed, or commercially exploited
- This is both a policy commitment and a technical design principle — the system should be architected so that data collection for AI purposes is impossible without a deliberate, opt-in user action

### Why This Matters

The target user is ethically attuned. They left Spotify over an ad. They will notice and care if MysteryMixClub ever feels extractive. Artist distrust of AI features is real and growing; honoring that distrust is part of being the platform these users actually want.

---

## What This Is Not

- A Spotify replacement or music streaming service
- A social network or public platform
- A music recommendation algorithm
- A competitive product trying to win on Music League's terms

---

## Success Looks Like

A friend group where the Spotify holdout, the casual listener, the grief-round player, and the competitive music nerd can all be in the same league, every round, without anyone feeling excluded, punished, or compromised.

---

*Next document: `personas.md`*
