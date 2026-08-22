# ADR 0020: Wire Flaught's full review (deterministic + LLM) into CI

**Status:** Accepted
**Date:** 2026-08-22

## Context

ADR 0019 reinstalled Flaught locally (deterministic tools only, run by
hand) and deliberately deferred CI integration: "Wiring Flaught into
`ci.yml` ... is a separate step with its own tradeoffs (permissions,
secrets, blocking-vs-advisory gating) and should get its own ADR when
done." All four findings clusters that surfaced during that local run have
since been fixed for real (`MysteryMixClub-2nz5`, `xywe`, `uqvr`, `d8hz`) —
`develop` is currently clean against `flaught review --no-llm`.

This ADR covers turning on the LLM pass in CI, which also means the first
CI integration of Flaught at all since the ADR 0018 revert (the
deterministic-only work stayed local).

Three things needed a decision, not just an implementation:

**Provider.** `.advreview.yml` already defaults to `provider: groq`. Since
Claude authors most of this repo's code (this session included), reviewing
with Anthropic's own models would reproduce exactly the self-review blind
spot Flaught's README describes as the reason it exists ("a model
reviewing code it wrote itself tends to agree with its own choices").
Groq stays the reviewer.

**Permissions.** `ci.yml`'s workflow-level `permissions: contents: read` is
deliberate least-privilege (see the comment above that block, predating
this change). Posting a PR comment needs `pull-requests: write`, which
this ADR scopes to the new `flaught` job only via a job-level
`permissions:` override — the frontend and backend jobs keep
`contents: read`.

**Gating.** Whether Flaught's severity gate (exit 1) should block merge.
ADR 0017's original landing chose artifact-only, non-blocking, and that
choice held up — the gaps that led to the ADR 0018 revert were ad hoc
config drift, not a blocking-related incident. The LLM pass is
additionally probabilistic (an LLM's phrasing and false-positive rate
vary run to run) in a way the deterministic tools aren't, so blocking
merge on it with zero track record is a worse starting point than
deterministic-only was. This lands non-blocking again: the job always
exits 0 regardless of findings, surfacing them via a PR comment and a
JSON artifact.

**Monorepo layout.** Flaught's own quickstart docs assume a single
`package.json` at repo root. This repo's root `package.json` only has a
`prepare: husky` script — no `test`/`lint` — with the real toolchains in
`frontend/` and `backend/`. Left as-is, Flaught's linter and vuln-scanner
auto-detection would silently no-op (find no `eslint`/`ruff`/`node_modules`
at the root and skip, per "all tools degrade gracefully"), quietly losing
most of the deterministic coverage this ADR is trying to add to CI. The
new job installs both toolchains (`npm ci` in `frontend/`,
`pip install -e ".[dev]"` in `backend/`) before running `flaught review`
from the repo root.

## Decision

Added a `flaught` job to `ci.yml`, triggered on the same `pull_request`
event as the existing jobs (`main`/`develop`). Steps, mirroring Flaught's
own documented "full" GitHub Actions workflow
(`docs/github-actions.md` in `flaught/core`) and this repo's SHA-pinning
convention from `MysteryMixClub-2nz5`:

1. Checkout (`fetch-depth: 0` — Flaught needs the base ref's history)
2. Set up Node + Python
3. `npm install -g @flaught/core`
4. `pip install semgrep`
5. `npm ci` in `frontend/`, `pip install -e ".[dev]"` in `backend/` —
   the monorepo-layout fix above
6. `flaught review --output findings.json --pr-description "<PR title>"
   --quiet`, `GROQ_API_KEY` from the existing repo secret,
   `continue-on-error: true` so a tool fault never fails the job
7. Upload `findings.json` as an artifact (`if: always()`)
8. Comment the report body on the PR (`gh pr comment`, `--no-llm` re-run
   for the comment body — same pattern and same rationale as Flaught's own
   docs: avoids a second LLM call per PR just to render markdown)

No step ever runs `exit 1`. `GITHUB_TOKEN`'s default permissions provide
the comment step's write access via the job-level override; no new secret
needed since `GROQ_API_KEY` already exists in the repo (added under ADR
0017, unused since the revert until now).

## Consequences

- **Every PR now gets Flaught's full review** (deterministic + LLM),
  visible as a PR comment and a downloadable JSON artifact — but it can't
  block a merge, by design, for this first landing.
- **`ANTHROPIC_API_KEY` and `OLLAMA_API_KEY` remain in repo secrets,
  unused.** Only `GROQ_API_KEY` is read by this job. Removing the other
  two is still fine per ADR 0018's note but isn't done here.
- **New scope on one job:** `pull-requests: write`, previously absent
  from every job in `ci.yml`. Confined to the `flaught` job.
- **CI runtime increases** by roughly the LLM call's latency plus two full
  dependency installs (`npm ci` + backend venv) the job wouldn't otherwise
  need — accepted as the cost of real deterministic-tool coverage rather
  than a silent no-op.
- **Findings will need triage on real PRs**, same as the local run
  surfaced 30 findings against `develop`'s existing code. Expect the first
  several PRs after this lands to carry LLM-asserted comments that need a
  dismiss-or-fix decision, same as the four bd issues this session's local
  run produced.

## Revisit if

The non-blocking gate should tighten to blocking once there's a real
track record of low false-positive rate on actual PRs — that's a new
decision (probably just an edit to the job's exit-code handling, but
significant enough to warrant its own short ADR per this doc's own
"Revisit if" convention) not a retroactive edit to this one.
