# ADR 0007: Add Google Sign-In and password login as additional auth methods, magic link stays

**Status:** Accepted
**Date:** 2026-07-27

## Context

Magic link is currently the *only* sign-in method (`docs/technical/technical-design.md`
§5) — no password field exists anywhere in the schema, and no OAuth provider
integration exists in the codebase. It has become the #1 user complaint: the
round-trip to an inbox (open a new app/tab, find the email, sometimes wait on
delivery) is friction every single login, not just at signup.

Alternatives considered:
- **Replace magic link entirely** (dropped): a bigger migration for existing
  users, and doesn't actually remove the email dependency — password reset
  still needs a working email flow, so the "no more waiting on email" benefit
  is smaller than it looks. Also removes a working, zero-password-to-leak
  option for users who are happy with it.
- **Restrict the Google option to @gmail.com addresses only** (dropped):
  conflicts with the project's platform-agnostic posture and would silently
  exclude Google Workspace users (own-domain email on Google's backend) for
  no real benefit — "Sign in with Google" conventionally means any
  Google-managed account, not literally gmail.com.

## Decision

Add two new sign-in methods **alongside** magic link, which remains fully
supported and unchanged:

1. **Google OAuth** ("Sign in with Google") — any Google-managed account, not
   restricted to @gmail.com.
2. **Email + password**, with a standard forgot/reset-password flow (which
   still uses Resend, the way magic link does today).

All three methods coexist on the login screen. Existing accounts are
unaffected by default — a user who never touches this stays on magic link
exactly as before. Password/Google become opt-in additions an existing user
can attach to their account from settings (set a password, or link a Google
identity), not a forced migration. New signups can use any of the three
methods, and all three still go through the existing invite/waitlist gate —
none of them bypass invite-only access.

`users` gains two new nullable columns: `password_hash` and `google_id`
(unique). Nullable because most accounts will carry only a subset of the
three identities (magic-link-only accounts have neither).

Google's official "Sign in with Google" button (their logo, colors, type) is
required by Google's branding terms and cannot be reskinned into the Sage/DM
Mono system. It is a second standing exception to the one-Rust-style
"restrained palette" posture, alongside the nav brand mark exception in
`docs/design/style-guide.md` — documented there, not treated as drift.

## Consequences

- Three sign-in paths to build, test, and maintain going forward instead of
  one. More auth surface area = more places a future bug can hide (e.g. the
  existing rate limiting only covers `/auth/request` today; the new password
  login endpoint needs its own brute-force protection from day one).
- New deployed secrets: `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` (staging +
  prod), via the standard secret-onboarding process in `docs/ci-cd.md`.
- New external dependency: a Google Cloud OAuth client/consent screen. Because
  the app already has live users, the production OAuth client will need
  Google's verification review for the `email`/`profile` scopes at that user
  count — this can add lead time outside engineering's control and should be
  started early, not treated as a same-day deploy step.
- The refresh-token cookie is already `SameSite=Lax` (MYS-91), specifically so
  a session survives a cross-site OAuth-provider return — no auth-cookie
  change needed for the Google flow to work.
- `magic_link_tokens` and the existing `/auth/request` / `/auth/verify`
  endpoints are unchanged — no deprecation, no migration for accounts that
  never touch the new methods.
- Style guide gets a second documented button-styling exception (Google's
  button) alongside the nav brand mark exception.

## Revisit if

- Magic-link usage drops to near-zero after this ships — worth a future ADR
  on whether to actually deprecate it rather than carry three permanent paths.
- Google's verification review materially blocks the rollout timeline —
  worth reconsidering whether Google ships first, gated behind a feature flag,
  while password ships independently.
