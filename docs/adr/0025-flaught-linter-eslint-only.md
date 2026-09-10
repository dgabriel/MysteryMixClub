# ADR 0025: Flaught's linter tool covers JS only, via an explicit command

**Status:** Accepted
**Date:** 2026-09-10

## Context

`MysteryMixClub-ta06` tracked a bug since PR #276's first real Flaught CI
run: the deterministic `linter` tool always self-reported "not run — is it
installed and on PATH?", even though `semgrep` and the vulnerability
scanner ran correctly in the same job, and the job installs both
toolchains (`npm ci`, `pip install -e ".[dev]"`) beforehand.

An earlier scoping pass (2026-09-09, this doc's own bd notes) ruled out the
original PATH theory: `eslint`/`ruff` being genuinely reachable on `PATH`
made no difference. The real cause, confirmed by direct reproduction: bare
`eslint` invoked from the repo root can't find `frontend/eslint.config.js`
— ESLint's flat config resolves relative to the invoking directory, not an
explicit path, and this repo's config lives inside `frontend/`, not at
root. Flaught has no per-tool `cwd` option (`docs/configuration.md`
confirmed), and treats that crash the same as "binary not found," failing
the *entire* linter tool rather than reporting partial per-language
results — a working `ruff` never got credit either.

Fixing the crash alone (`cd frontend && eslint .`) wasn't sufficient on its
own: ESLint's default human-readable output produced a nonzero exit but
zero results Flaught could parse into findings. `--format json` was
required to get real, individually-attributed findings out of it.

`tools.linter.command` is a single string — no array, no per-language
multi-command support (confirmed via `docs/configuration.md`). A combined
shell chain (`eslint ...; ruff ...`) was tested directly: it runs without
crashing, but produces `raw_findings_count: 0` — two different tools' JSON
outputs concatenated back-to-back isn't valid JSON, so Flaught's parser
(built for one known tool's shape at a time) can't extract anything from
it.

## Decision

Set `tools.linter.command` explicitly:

```yaml
command: 'sh -c "cd frontend && npx eslint --format json ."'
```

Flaught executes `tools.linter.command` through a real shell (confirmed
empirically — `cd` and `&&` work), which is what makes this fix possible at
all without a native `cwd` option.

This covers **JavaScript/TypeScript only**. Python is not left
unenforced — `ruff check` + `ruff format --check` already run for real in
the backend CI job, pre-commit (`lint-staged`), and pre-push (ADR 0024's
path-scoped version). Flaught's own dedicated linter pass is one signal
among several, not the only one, for either language — the same reasoning
already applied to `dependency_sanity`/`test_weakening` staying on in ADR
0023 despite `ruff`/`mypy` overlap.

## Consequences

- Flaught's linter tool now genuinely runs and reports real findings,
  closing a gap that had been silently present since the tool's first CI
  landing.
- **Five real, pre-existing findings surfaced immediately** on the current
  codebase (two `react-refresh/only-export-components` in
  `AuthedLayout.tsx`/`useAuth.tsx`, two `react-hooks/set-state-in-effect` in
  `MixDetailRoute.tsx`/`VerifyRoute.tsx`) — all `low` severity, comfortably
  under the `noise_budget.low: 20` threshold (ADR 0023), so the gate
  doesn't trip on them. Left undismissed, not silently fixed, by this ADR;
  tracked as its own bd issue rather than folded into a linter-plumbing fix.
- **Python gets no dedicated Flaught-native linter pass.** If that gap
  matters enough later, it needs a different mechanism than
  `tools.linter.command` — Flaught doesn't support what would be needed to
  run both cleanly through its current single-command schema.
- Verified locally against `develop`'s real current state, not just a
  synthetic test, before shipping — same "run it against real state first"
  discipline ADR 0023 established for the version-bump.

## Revisit if

- Flaught adds native multi-command or per-language `tools.linter` support
  — re-evaluate whether Python can get its own dedicated pass without the
  JSON-concatenation problem this ADR hit.
- The JS-only linter pass proves to have a real false-negative cost (a bug
  it would have caught on the Python side) worth chasing a workaround for,
  e.g. a second custom-tool entry if Flaught's config schema grows one.
