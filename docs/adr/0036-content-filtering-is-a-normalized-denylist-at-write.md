# 36. Content filtering is a normalized denylist enforced at write time, scoped to hate and harassment

Date: 2026-08-24
Implemented in branch: `feature/MysteryMixClub-4vii.43-content-filtering-method-for-free-text-notes-guide`
MysteryMixClub-4vii.43, blocked by MysteryMixClub-4vii.13 (4vii.46 is the App Store release gate).

Guideline 1.2's third prong — "a mechanism to filter objectionable material" —
needs something that acts *before* other members can see objectionable text;
reporting (4vii.13) and blocking (4vii.42) are both after-the-fact. This ADR
fixes what that mechanism is, and just as importantly what it deliberately
isn't.

## Assumptions

- The surfaces in scope are the ones where a member writes text that other
  members will read: display name, club name + description, mix theme +
  description, submission note, note body.
- App Review tests this the way a person would: try obvious slurs and the
  canonical abusive phrases, through the obvious evasions (casing, leetspeak,
  repeated letters, accents, dotted/spaced-out letters).
- A reviewer never tests with "this fucking slaps", and an app that 422s that
  sentence would be broken for its actual users.

## Decision

- **Server-side denylist** (`app/services/content_filter.py`), applied at every
  in-scope *write*: display name (PATCH /users/me — the only write path),
  club create + patch, mix theme/description patch, submission note
  (create / replace / note-only edit), note body (create + edit). A blocked
  write means the text never exists, which is the strongest reading of
  "filtered before other members can see it".
- **Normalization before matching**: NFKD + diacritic strip, lowercase, a
  small leetspeak map (0→o, 1→i, 3→e, 4→a, 5→s, 7→t, @→a, $→s, plus Cyrillic
  look-alikes), repeated-letter run collapse, tokenize on non-alphanumerics.
  A run of single-letter tokens ("r.e.t.a.r.d", "r e t a r d") is also
  checked in joined form. The denylist itself is pre-normalized through the
  same pipeline, so both sides compare collapsed (e.g. "kill" vs stored
  "kil").
- **Whole-token matching (+ plain +s/+es plurals), not substring.** This is
  the decision that makes a denylist livable in a music app: "bass",
  "class", "assassin", "Scunthorpe", "cumulonimbus" all pass. Substring
  matching would be a false-positive generator and a support burden.
- **Scope is hate and harassment, not general profanity.** The list is racial/
  ethnic/religious slurs, homophobic/transphobic slurs, ableist slurs,
  sexual-violence and explicit pornographic terms, and targeted-harassment
  phrases ("kill yourself", "kys", "go die"). "Fuck", "shit", and the rest of
  the register this user base actually talks in are allowed — they are not
  what creates the abusive environment 1.2 is aimed at, and filtering them
  would punish product-appropriate speech to satisfy no one.
- **One generic rejection** — 422 with `that text isn't allowed here — try
  something else.` — never echoing the flagged term (that would teach evaders
  which normalization to route around). Raised as an HTTPException from the
  route handlers (not as a Pydantic field-validator 422) so `detail` stays a
  plain string and the frontend's `readErrorMessage` surfaces it verbatim in
  the existing form-error slots. No new frontend work.
- **Deliberately unfiltered**: song title/artist are catalog data chosen from
  search results, not authored text (policing edge-case catalog titles is
  reporting's job); report `detail` is visible only to operators, never to
  other members; admin/waitlist paths aren't member-visible UGC.

## Alternatives Considered

- Moderation API / LLM classifier (e.g. OpenAI moderation, Perspective):
  stronger recall, but adds a network dependency, per-call latency and cost,
  a privacy question (member text leaves the system), and its own failure
  modes on music-club slang. Massive overkill for invite-scale clubs and
  short free-text fields; revisit only if the denylist visibly leaks.
- Substring matching on the same list: fails Scunthorpe immediately in this
  app's actual vocabulary ("bass", "class"). Non-starter.
- Full profanity lists (fuck/shit/ass/...): the false-positive cost lands on
  the core user experience, not on abusers. The product call is that abusive
  *targeting* is what's filtered; tone is the club's own business (and
  reporting/blocking cover personal taste).
- Client-side validation: trivially bypassed, and duplicates policy in a
  place we can't revoke. Server-side only; the client just renders the
  message.
- Hold-for-review queues: nothing to review against — there is no moderator
  UI, and invite-scale clubs don't need one yet. Rejection at write is
  simpler and stronger.

## Consequences

- Evasion holes accepted as out of scope for v1: obfuscation beyond the
  mapped homoglyphs (creative spacing mid-word like "re tard", unicode
  beyond the mapped Cyrillic look-alikes, slurs not on the list). The
  realistic ceiling of any denylist; reporting + blocking catch what the
  filter misses.
- The list lives in source and in git history; that's normal for this class
  of filter and the terms appear only as data, never in UI copy.
- Tightening (new terms, new normalization, a profanity tier, a screening
  API) is a one-file change behind `reject_if_flagged`; every surface already
  funnels through it.
- 4vii.46's 1.2 story is now complete on the prevention side: filter (this)
  + report (4vii.13) + block (4vii.42) + contact + ToS.

## Revisit if

- We see real evasion (spaced letters mid-word, unmapped unicode, terms not
  on the list) in report traffic — extend normalization or add terms.
- Reports show the register call was wrong (generic profanity genuinely
  driving complaints) — add a stricter tier.
- Scale or public discovery makes per-write denylist insufficient — move to
  a screening API; the call sites don't change.
- Multi-word phrases need fuzzy handling (inserted words between phrase
  parts) — the current implementation only matches adjacency.
