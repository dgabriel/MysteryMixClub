# ADR 0034: Bind push registrations to the login session

**Status:** Accepted
**Date:** 2026-09-20

## Context

Push registration (`POST /users/me/push-token`) is authenticated by the access
token alone. An access token is a stateless JWT valid for 60 minutes, and logout
invalidates the *session* (the refresh token), not the access tokens already
issued. Two consequences, found in independent review of the push work
(`MysteryMixClub-4vii.36`):

- A registration upload can be in flight when logout runs. The client's own
  cleanup (`DELETE /users/me/push-token`, after waiting a few seconds for the
  upload) cannot undo an upload the server has already accepted, and a client
  timeout or `AbortController` does not cancel a request the server is already
  processing. The upload can commit after the DELETE and recreate a row for an
  account that has signed out, which then keeps receiving pushes on that phone.
- The same shape applies to switching accounts on one phone: an older login's
  late upload can overwrite the next account's ownership of the device token.

`POST /auth/logout` did not delete device rows at all, so the client's `DELETE`
was the only cleanup, and a failed one was silent.

The refresh cookie cannot be used to tie the request to a session on this route:
it is scoped to `Path=/api/v1/auth` on purpose and is not sent to
`/users/me/push-token`.

## Decision

**The access token names its session, and device registration is bound to it.**

- `create_access_token` adds a `sid` claim (the session's id). Both mint sites
  already have the session: session creation and `/auth/refresh`.
- `POST /users/me/push-token` requires the `sid` session to belong to the caller
  and be live (not invalidated, inside the refresh lifetime -- one shared rule,
  `session_is_live`, also used by `/auth/refresh`). It reads the session
  `FOR SHARE`; `/auth/logout` reads the same row `FOR UPDATE`, invalidates it and
  deletes that session's `device_push_tokens` rows in one transaction. So a
  registration either commits before logout (and logout deletes it) or runs after
  and is refused with the neutral 401. It cannot recreate a row after logout.
  `/auth/logout-all` and a password reset (both go through
  `_invalidate_all_sessions`) likewise drop the account's signed-out devices.
- **Lock order for everything that touches device rows or the session-liveness
  lock: users row -> session rows -> device rows.** Scoped on purpose: an earlier
  draft claimed one order across *all* writers of these tables, and five review
  rounds showed that cannot be established piecemeal (each round found another
  pair, the last two in code this work never touched). What is guaranteed is
  narrower and is tested:
  - Registration takes `FOR KEY SHARE` on the caller's `users` row (re-reading
    it under the lock: a soft-deleted user, or a hard-deleted one whose row is
    gone, is refused with the neutral 401), then the session `FOR SHARE`, then the
    device row. The first version took the session first and reached the users row
    later through the device insert's foreign key, and deadlocked with account
    deletion.
  - `FOR KEY SHARE` is the weakest mode that conflicts with account deletion (a
    key update on the unique `email`, exclusive) and it does **not** conflict with
    changes to non-key columns (a profile edit, a password change, a ToS
    acceptance), so ordinary account activity never blocks a registration. The
    SQLAlchemy trap: `with_for_update(key_share=True)` alone compiles to
    `FOR NO KEY UPDATE`; `read=True` is needed as well.
  - Logout, logout-all and a password reset take a session and then its device
    rows. Account deletion and the hard delete now delete devices *after*
    sessions (they used to do the reverse and deadlocked with logout).
  - Account deletion deletes its reset tokens before touching the user row,
    because password reset takes its token row and then the user (a cycle that
    predates this work and that the stress test exposed).
  - A reset whose token row a racing request already consumed now gets the
    neutral 401 (it used to raise `StaleDataError`, a 500).
- A token already held by another session is only taken over by a session at
  least as new (compared on `sessions.created_at`, a server clock). An older
  login's late upload gets 409 and cannot take a device back from a newer one.
- `device_push_tokens.session_id` is a nullable foreign key, `ON DELETE SET NULL`
  (an old session being purged must not silently remove a device that is still
  registered). The migration is additive.
- Tokens issued before the claim existed have no `sid` (they expire within an
  hour of the deploy). Such a token may register a new device or re-register an
  *unbound* one, but never takes a device that a session owns (409): with no
  session to compare, a stale request could otherwise overwrite, and unbind, a
  newer sign-in's device. (A first draft let them take over unconditionally; an
  automated review flagged it and it was tightened.)

The client's own `DELETE` stays as belt and braces, and its 5-second wait for an
in-flight upload stays as a best effort; correctness no longer depends on either.

## Consequences

The guarantee is enforced where the data lives, so it holds regardless of client
timing, retries, or a crashed app. Cost: a schema column, a claim on every access
token (harmless to every other route, which ignores it), and one more query and
row lock on registration -- a route hit roughly once per login, not a hot path.

How it was tested, including what was wrong the first time. The lock argument
is exercised on **two real connections** (`test_push_token_session_concurrency.py`,
the `real_*` fixtures ADR 0005 keeps for exactly this): each ordering is forced
(a second connection holds the lock, the request under test is shown to block,
then the outcome is asserted), plus an unforced register-vs-logout race. Removing
the registration's `FOR SHARE` fails three of them.

Each ordering above is pinned by a deterministic test that follows the reported
interleaving through the real route or the real function (a third connection
holds a lock so the two requests queue in the order that produces the cycle), and
reverting any one of the fixes fails a named test. Because this class of bug kept
recurring, there is also a seeded stress test: 25 rounds, each firing a random
subset of the user-facing writers at one account at once (register x2,
unregister, logout, logout-all, password reset, refresh, password login, profile
edit, account deletion; logout always included). Any exception or 5xx fails it, a
deadlock fails via a timeout instead of hanging, and the end state is asserted:
no device may outlive its session or its account. It has teeth: putting account
deletion's token or device order back the wrong way reports a deadlock every
time, and making logout skip its device delete fails the end-state check every
time. (Each round runs a random *subset* on purpose: account deletion, logout-all
and a reset each remove all of a user's devices, so a round that always included
them could never show a device that survived a plain logout.) These tests are
written to fail rather than hang: a failing assertion releases its locks and lets
pending tasks finish before any session closes.

An earlier draft of this ADR said the harness could not test this and relied on
tests over a shared transaction. That was wrong, and those tests hid a real bug:
the takeover subquery was not tied to the conflicting row (SQLAlchemy does not
auto-correlate inside `ON CONFLICT ... WHERE`), so once two or more bound rows
existed it raised "more than one row returned by a subquery" and registration
returned 500. Every test had at most one bound row when a conflict fired. The
subquery now names the conflicting row's own column, and the takeover tests
deliberately hold several bound rows; reintroducing the bug fails four of them.

## Known limits

- **Lock-order gaps this work does not close** (found by review, reproduced,
  none involve device rows, and all predate it): a password login that clears
  *pre-existing* failed-attempt rows takes them before the session insert (which
  key-shares the user row) while account deletion takes the user row before them;
  Google/Apple identity relinking takes `auth_identities` before the user row
  while account deletion takes them the other way round; and the admin eject
  (`hard_delete_users`) of a **live** account can deadlock with, or fail an FK
  against, that user's own in-flight request (a vote, a registration): develop
  failed with an FK error there, so it is no worse, and the scheduled purge only
  touches soft-deleted accounts, which cannot sign in. Each fails one of the two
  requests cleanly (the transaction rolls back; a retry succeeds). Tracked as a
  follow-up audit rather than piecemeal fixes.
- **The hard delete now also removes a live account's devices and linked
  identities** (`auth_identities.user_id` and `device_push_tokens.user_id` have no
  `ON DELETE`, so the admin eject of a live account raised an `IntegrityError`).
  Found while reviewing the lock order; fixed in the same function.
- **Rows that exist at deploy time have no session.** They are removed on
  logout only once the app re-registers and binds them (which happens on the
  next launch after the update); until then only the client's own `DELETE`
  cleans them, as before. Likewise a device token registered with an access token
  issued before the claim existed (at most an hour) is unbound.
- **Sessions that simply expire** (30 days, never logged out) are not swept; their
  rows stay until the token is re-registered or APNs retires it.
- **A device registered with a session-less token is unbound.** A token with no
  `sid` (issued before the claim existed, at most an hour) can create or re-register
  only unbound rows, so its device is not removed by logout until the app
  re-registers with a token that names a session. Transitional and self-healing
  (the next refresh mints a `sid`).
- **`sessions.created_at` is the start of the login transaction**, so two logins
  on one phone within the same instant compare arbitrarily. Theoretical, and the
  outcome (which of two simultaneous logins keeps the device) is harmless.
- The sweep for `/auth/logout-all` and a password reset is scoped to rows whose
  session is signed out or absent, so a device a brand-new login registered in the
  gap is kept rather than lost.

## Not decided here

Access tokens are still not revoked at logout for any other route; this ADR does
not change that trade-off (a stateless JWT is the point of the design). Only the
one route whose effect outlives the session now checks it.

## References

- `docs/technical/technical-design.md` → Session Management
- `docs/ios/README.md` → "Which account a registration belongs to"
- [ADR 0005](0005-test-isolation-transaction-rollback.md)
- `MysteryMixClub-4vii.32` (registration), `.33` (retirement), `.36` (this)
