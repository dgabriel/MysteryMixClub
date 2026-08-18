# ADR 0017: Add Flaught adversarial code review as a CI job

**Status:** Accepted
**Date:** 2026-08-18

## Context

CI today catches what deterministic tools catch: lint, types, and whatever
the test suite happens to exercise. Nothing in the pipeline does the job a
skeptical human reviewer does — asking "does this actually do what the PR
claims," flagging scope creep, or noticing a test that would pass on the
pre-change code too. `@flaught/core` (Dawn's own package, published to npm)
is a CLI built for exactly that gap: a five-stage pipeline (deterministic
tools → LLM adversarial pass → test inversion → scope-creep detection →
severity gate) that emits a JSON findings artifact per PR, with every finding
tagged `deterministic` or `llm-asserted` so the artifact never overstates its
own certainty.

Adding it means three things that cross the "write an ADR" bar on their own:
a new third-party vendor dependency (an LLM provider call per PR), a new
GitHub Actions secret, and a CI job whose findings are inherently probabilistic
rather than deterministic like the rest of the pipeline.

Three scoping questions had to be settled up front (2026-08-18):

- **PR comments vs. artifact-only.** Posting PR comments needs
  `pull-requests: write`, a real scope increase on a workflow whose
  `permissions:` block is currently `contents: read` by deliberate design
  (see the comment above it in `ci.yml`, tied to code-scanning findings
  #1/#3). Decided: artifact-only for now — no permissions change.
- **Deterministic-only vs. full LLM pass.** `--no-llm` needs no secret and
  no vendor call, but skips the adversarial pass that's the actual point of
  the tool. Decided: full LLM pass via Anthropic, accepting the new secret.
- **Blocking vs. non-blocking.** Decided: non-blocking (`continue-on-error:
  true`), matching the existing `npm audit` / `pip-audit` pattern in
  `ci.yml` — surface findings without letting a new, unproven tool gate
  merges.

## Decision

New `flaught` job in `.github/workflows/ci.yml`, sibling to `frontend` and
`backend`, triggered by the same `pull_request` → `main`/`develop` event:

- Installs `@flaught/core` fresh in the job (`npm install -g`), same ad hoc
  pattern as `pip-audit` — not a pinned `package.json` dependency.
- Checks out with `fetch-depth: 0` so `origin/<base_ref>` resolves for the
  diff (a shallow checkout only has the PR's own commits).
- Runs `flaught review --base origin/${{ github.base_ref }} --pr-description
  "${{ github.event.pull_request.title }}" --output flaught-findings.json
  --quiet`, then uploads `flaught-findings.json` via
  `actions/upload-artifact@v4` (`if: always()`, matching the
  `backend-coverage` artifact's pattern).
- Reads `ANTHROPIC_API_KEY` from a new GitHub Actions secret. Provider is
  configured in a committed `.advreview.yml` at repo root: `provider:
  anthropic`, `model: claude-sonnet-5`, `api_key_env: ANTHROPIC_API_KEY`.
  Stack is declared explicitly (`fastapi` + `react`, `runtime: mixed`)
  rather than left to auto-detection, since the repo genuinely mixes both.
- `continue-on-error: true` on the review step — exit code 1 (findings above
  the severity gate) or exit code 2 (config/LLM error, e.g. no secret on a
  fork PR) both fail only that step, never the required merge check.
- No workflow `permissions:` change — the job stays inside the existing
  `contents: read` grant.

## Consequences

- **A new secret to provision.** `ANTHROPIC_API_KEY` must be added under
  GitHub → Settings → Secrets and variables → Actions before the job does
  anything beyond fail step 3 harmlessly. This is a workflow-only secret —
  it does not go through the Droplet `staging.env`/`prod.env` routine in
  `docs/ci-cd.md`, since neither running app ever reads it.
- **A per-PR LLM API cost**, ongoing, scaling with PR volume and diff size —
  worth watching if PR frequency grows.
- **Findings are not currently visible on the PR itself** — only as a
  downloadable Actions artifact. Revisit if that friction makes the tool go
  unread in practice.
- **A red Flaught step never blocks merge today.** Real signal could get
  ignored the same way a chronically-red non-blocking check gets ignored
  elsewhere; this is the deliberate cost of "prove it out before gating."
- **The tool's own findings carry an explicit caveat** (per its README): the
  artifact is evidence scrutiny *occurred*, not that findings are *correct*.
  LLM-asserted findings can hallucinate; deterministic-tool findings have
  their own false-positive rates. Treat it as a prompt for human review, not
  ground truth.

## Revisit if

- Findings prove reliable enough over a stretch of PRs to flip the severity
  gate from non-blocking to blocking.
- PR-comment visibility turns out to matter enough to justify the
  `pull-requests: write` permission increase.
- LLM API cost or latency becomes a real burden — at that point, evaluate
  `--no-llm` for routine PRs with the full pass reserved for larger diffs,
  or a cheaper/faster model.
