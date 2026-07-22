# ADR 0001: Feature flags are plain env-driven booleans, not a flag service

**Status:** Accepted
**Date:** 2026-07-21

## Context

MysteryMixClub occasionally needs a behavior that's environment-specific or
meant to be temporary — an email sink for staging testing
(`EMAIL_REDIRECT_TO_TEST`), a public waitlist standing in for the normal
invite flow while the app is pre-launch. These need to be turned on/off
without a code revert or redeploy of app logic, and tested in both states
before shipping.

The alternative — a flag service with per-user or percentage-based
targeting, remote config, kill switches independent of deploys — is
overkill for a single-team, invite-only app at this stage. It adds an
external dependency (or a bespoke admin UI + storage layer) to solve a
problem this app doesn't have yet: nobody needs to flip a flag for 5% of
users, or without redeploying, or per-user.

## Decision

Feature flags are plain boolean settings on `backend/app/config.py`
(`Settings`), sourced from environment variables via `get_settings()`. No
flag service, no runtime remote config, no per-user targeting.

Conventions (full detail in `docs/feature-flags.md`):
- Default `False` — off is the safe path in production.
- Fail safe — if a flag is on but its companion config is missing, choose
  the non-destructive behavior.
- One flag, one clearly-named boolean; document it in the registry on the
  same PR that introduces it.
- Test both states before merging.
- Deploys env vars through the existing per-environment paths (Droplet
  `staging.env`, App Platform env block) — same mechanism as any other
  config, no new infrastructure.

## Consequences

- **Turning a flag on/off in production requires touching the deployed
  env** (Droplet SSH + service restart, or the DO dashboard) — there's no
  self-service admin toggle. Acceptable at current scale; revisit if flags
  need to change faster than a deploy/restart cycle allows.
- **No gradual rollout** (percentage-based, cohort-based). Every flag is
  all-or-nothing per environment. Fine for binary temporary features; would
  need a real decision (and likely a new ADR) if the product ever needs
  A/B-style rollout.
- **Flags accumulate as plain settings** — nothing prunes a flag once its
  feature is permanent or removed. The registry in `docs/feature-flags.md`
  is the source of truth for what's live; a flag whose feature has shipped
  for good should be deleted from `config.py` and the registry in the same
  PR that removes the conditional, not left as dead config.

## Revisit if

Per-user or percentage targeting becomes an actual product need, or flags
need to change without a deploy/restart — at that point, evaluate a real
flag service rather than growing this pattern to fit.
