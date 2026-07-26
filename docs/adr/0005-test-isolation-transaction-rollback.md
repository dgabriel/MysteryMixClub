# ADR 0005: Backend test isolation moves from per-test TRUNCATE to transaction rollback

**Status:** Accepted
**Date:** 2026-07-26

## Context

Flagged by Dawn 2026-07-23 (`MysteryMixClub-prdicl`, Linear MYS-235): pushing
even a small, frontend-only PR took several minutes locally before CI even
started, dominated by the pre-push hook's full backend suite. This is
friction on every single push, not just large changes.

Investigation (not guesswork — see the actual profiling) found the suite
itself is not slow in the way "1066 tests" suggests. `--durations=40` showed
no slow individual test — the slowest single item was 0.54s, and the suite
runs at only ~32% CPU over its ~3m37s wall-clock, meaning it's I/O-bound, not
compute-bound. The actual cost is `backend/tests/conftest.py`'s function-scoped
`engine` fixture, which runs a `TRUNCATE ... CASCADE` on 9 tables **before and
after every one of 1066 tests**. Benchmarked in isolation against the real
test database: ~166ms of a measured ~172ms per-test fixture cost is Postgres
fsync'ing the TRUNCATE's WAL record (default `fsync=on`,
`synchronous_commit=on`) — correct, safe defaults for a real database, wrong
defaults for a database that's fully rebuilt every test session and never
needs to survive a crash. That single cost accounts for roughly 80% of the
entire suite's wall-clock time.

Alternatives considered:

- **`pytest-xdist` (`-n auto`) to parallelize across cores.** Investigated and
  rejected for now. This repo's tests share one real Postgres database
  (`mysterymixclub_test`); two full-suite pytest invocations running
  concurrently against it are confirmed to deadlock
  ([[project_serial-test-runs]]). `conftest.py`'s schema setup
  (`Base.metadata.drop_all`/`create_all`, session-scoped, autouse) is not
  worker-safe as written — multiple xdist workers would independently race to
  drop/create the same tables in the same database, which is the identical
  failure mode already known to occur. Making xdist safe would need
  database-per-worker or schema-per-worker isolation: new provisioning logic
  in `docker-compose.yml`/CI, keyed off `PYTEST_XDIST_WORKER`, plus rewritten
  fixture teardown. That's real, ongoing complexity purely to re-run the same
  expensive TRUNCATE cost N times in parallel rather than removing it. Revisit
  only if wall-clock is still a real problem after the fixes below land.
- **CI job parallelization.** Not applicable — `.github/workflows/ci.yml`
  already runs the backend and frontend jobs in parallel (confirmed from job
  timestamps, not assumed). Splitting `ruff`/`mypy`/`alembic` (~12s combined)
  into their own job would net *lose* time: each new GitHub Actions job pays
  ~20-25s of fixed container/checkout/setup overhead before running anything.
- **Narrowing the pre-push hook to a lighter test subset.** Rejected for now.
  The hook running the full suite before every push is intentional, documented
  (`docs/git-hygiene.md`, [[feedback_targeted-test-runs]]), and — given the
  shared-DB deadlock constraint above — is part of what prevents a local run
  and a CI run (or two people's CI runs) from colliding. The friction being
  felt is overwhelmingly the fixture cost below, not the fact that the full
  suite runs; fix the fixture first and re-measure before touching this.

## Decision

Two changes, both landing together:

1. **Per-test database isolation moves from `TRUNCATE ... CASCADE` to
   transaction rollback** — the standard SQLAlchemy "join a session into an
   external transaction" pattern: each test begins one connection/transaction,
   binds the session to it via a `SAVEPOINT`, and rolls back at teardown
   instead of committing and truncating. Rollback never needs to fsync a
   durable write, so this removes the ~166ms/test cost at its root rather than
   spreading it across more workers. This touches the `engine`/`session`
   fixtures every one of the suite's tests depends on — that's exactly why
   this is an ADR and not a routine fixture tweak: it changes what "committed"
   means to every test in the suite, and any test that specifically asserts
   on cross-connection commit visibility needs to be checked against the new
   pattern, not assumed to keep working unchanged.
2. **Relax fsync/durability settings on the test-only Postgres**
   (`synchronous_commit=off`, `fsync=off` — via `docker-compose.yml`'s
   `mmc-postgres` command/config, and the equivalent for CI's Postgres service
   container) as a complementary, defense-in-depth fix — safe specifically
   because this database is fully rebuilt every session
   (`_schema`'s `drop_all`/`create_all`) and never needs crash durability.
   Note this Postgres container also serves local dev (not just tests); that's
   an accepted tradeoff since local dev data isn't precious either, but it's a
   deliberate, not accidental, scope expansion of the flag worth naming here.

`pytest-xdist` is explicitly **not** adopted by this decision.

## Consequences

- Every backend test's isolation guarantee changes from "the table was
  actually truncated" to "the outer transaction was rolled back." Behaviorally
  equivalent for the overwhelming majority of tests (each sees an empty table
  at the start, per SQLAlchemy's standard testing pattern), but any test that
  opens a **second** real connection and expects to see another connection's
  writes (uncommon, but possible with anything testing concurrent-access
  behavior — e.g. the `MysteryMixClub-y8r2ki` participation-cap race-condition
  test) needs to be checked explicitly against the new pattern, since a
  rolled-back outer transaction is invisible to a second connection in a way a
  real commit-then-truncate cycle was not.
- Local dev Postgres now runs with `fsync`/`synchronous_commit` off
  server-wide (see note above) — acceptable since local dev data is not
  precious and is easily rebuilt, but this must **never** be mirrored onto
  staging or prod Postgres, which need real durability. This is test/dev-only.
- `pytest-xdist` remains unadopted. A future contributor (or session) seeing
  the suite still runs serially should not "fix" that by reaching for `-n
  auto` without first reading this ADR — it was considered and deliberately
  deferred, not overlooked.
- `MysteryMixClub-e5f6` (aligning local vs. CI Postgres major version,
  16-alpine vs. 15) was noticed during this investigation and filed
  separately — unrelated to and not blocking this decision.

## Revisit if

- The fixture fix doesn't bring wall-clock down meaningfully in practice (i.e.
  the profiling assumption here turns out wrong once re-measured post-fix) —
  at that point, `pytest-xdist` with schema-per-worker isolation becomes worth
  the added complexity.
- The suite grows enough (new test count, or genuinely slow individual tests
  appearing in `--durations`) that per-test overhead is no longer the
  dominant cost — re-profile rather than assuming this ADR's numbers still
  hold.
