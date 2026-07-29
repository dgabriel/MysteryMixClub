# Instrumentation — shipped-issue timing collector

Tracks how long features take to ship and bugs take to fix.
Epoch zero: **2026-07-26**. Nothing earlier is backfilled, anywhere, ever —
see "What this cannot measure" below.

Status: **all five phases are built** (MysteryMixClub-ghal). The existing
`scripts/analysis/bd_velocity_analysis.py` is unrelated prior work and is
not touched by any of this — it analyzes bd issue data generally; this
collector is scoped specifically to shipped-issue timing from 2026-07-26
forward and will feed a rewrite of that script later, not replace it here.

## Non-negotiables this whole design follows

- **Zero bd-graph writes** anywhere in this collector, except `bd update
  <id> --claim` inside `scripts/bead-start.sh`. No bulk edits, no status
  rewrites, no backfilled `started_at`.
- **Every derived field traces to a raw event that is actually stored.** If
  a value can't be derived from something on disk, it's `null` — never a
  substituted nearby timestamp.
- **Hooks fail open.** Every hook script in `hooks/` wraps its entire body
  in a try/except, logs failures to `events/errors.jsonl`, and exits 0
  unconditionally. A bug in this instrumentation must never block or slow
  down a Claude Code session.
- **No network calls from any hook.** GitHub API enrichment is a separate,
  on-demand batch job (Phase 4, not yet built), never inline in a hook.

## Files

### `hooks/_common.py`
Shared helpers imported by every hook script: JSONL append (never rewrites
a line), git branch/head via a plain `git rev-parse` subprocess call (not a
library), the fail-open `safe_main()` wrapper, and error logging.

### `hooks/session_hook.py`
Registered in `.claude/settings.json` under both `SessionStart` and
`SessionEnd`. Appends one line per firing to
`.instrumentation/events/sessions.jsonl`:

```
schema_version, ts, event_type, session_id, cwd, git_branch, git_head, reason
```

`event_type` is `SessionStart` or `SessionEnd`. `reason` is only populated
if Claude Code's own payload happens to carry a `reason` field — as of
2.1.220 that's confirmed as a *matcher* value for `SessionEnd`
(`clear`/`resume`/`logout`/`prompt_input_exit`/`bypass_permissions_disabled`/
`other`), not confirmed as an actual payload field, so this is usually
`null` today. On `SessionStart`, this hook also drops the session id into
`.instrumentation/state/current_session` (atomic write) so other tooling in
the same session — the Phase 3 reviewer logger, once built — can find it
without guessing at an undocumented env var.

### `hooks/subagent_hook.py`
Registered under both `SubagentStart` and `SubagentStop`. Appends one line
per firing to `.instrumentation/events/agents.jsonl`:

```
schema_version, ts, event_type, session_id, agent_id, subagent_name,
model, input_tokens, output_tokens, duration_ms, exit_status
```

Verified against Claude Code 2.1.220's own docs (`code.claude.com/docs/en/
hooks.md`, checked 2026-07-29): the payload carries `agent_id` (unique per
invocation) and `agent_type` (the subagent's frontmatter `name` — e.g.
`developer`, `tester`, `reviewer`, `ui-agent`; stored here as
`subagent_name`), but **no model identifier, token counts, or duration**.

- `duration_ms` is derived, not handed to us: `SubagentStart` writes a
  timestamp marker to `.instrumentation/state/agent_<agent_id>.start`;
  `SubagentStop` reads and deletes that marker and subtracts. If the marker
  is missing (hook added mid-session, process killed between the two
  events, etc.), `duration_ms` is `null` — never backfilled from another
  timestamp.
- `model`, `input_tokens`, `output_tokens` are **always `null`** — confirmed
  unavailable in any Claude Code hook payload today. Kept as explicit `null`
  fields (not omitted) so every row has a stable shape. See "What this
  cannot measure."
- `exit_status` is read from a `stop_reason` field on the payload *if one is
  ever actually present* — no such field is documented as of 2.1.220, so
  this is `null` in practice today, but the code doesn't hardcode that
  absence in case Claude Code adds one later.

### `events/errors.jsonl` (not committed)
Every hook failure lands here: `schema_version, ts, hook_event_name, error,
traceback`. Hooks never surface these to the interactive session.

### `check_bead_trailer.py`
Called from the `commit-msg` git hook (both `.beads/hooks/commit-msg` and
`.husky/commit-msg`, chained after `commitlint`). Requires a `Bead: <id>`
trailer on every commit, validated against real bd issue ids (`bd show`,
local/read-only, no network) — except commits typed `chore`/`docs`/`ci`/
`style`/`build`/`revert`, and merge commits. Exit 1 blocks the commit; this
is the one piece of the whole design that's allowed to block, since its
entire job is enforcement (unlike the Phase 1 hooks, which must never
block).

### `../bead-start.sh`
The single entry point for starting work: syncs `develop`, creates
`feature/<id>-<slug>` (`fix/<id>-<slug>` for a bug), then claims the issue.
See the script's own header comment and `AGENTS.md`/`CLAUDE.md` for the full
convention.

### `log_review.py`
Called by the reviewer subagent (`.claude/agents/reviewer.md`, "Logging
your verdict" section) at the end of every review pass:

```
scripts/instrumentation/log_review.py <issue_id> <PASS|FAIL> <reason_code>
```

Appends one line to `.instrumentation/events/reviews.jsonl`:

```
schema_version, ts, issue_id, session_id, iteration_number, verdict, model, reason_code
```

- `issue_id` comes from the reviewer parsing its own current branch name
  (`feature|fix/<id>-<slug>`) — the reviewer is told explicitly not to guess
  it from commit text.
- `iteration_number` is **per issue, not per session**: 1 + however many
  prior `reviews.jsonl` records already exist for that `issue_id`, so
  rework across sessions still counts correctly. This is the rework signal.
- `reason_code` is a closed vocabulary (`security_issue`, `logic_defect`,
  `scope_mismatch`, `quality_issue`, `style_violation`, `clean`), enforced
  by the script — free text doesn't aggregate, and the eval framework this
  feeds later needs a fixed set of buckets.
- `model` is always `null` — same reason as `agents.jsonl`: nothing exposes
  which model the reviewer subagent is running under.
- Unlike the Phase 1 hooks, this script does **not** fail open — it's a
  normal command the reviewer runs deliberately, so a logging failure
  should be visible in its own transcript (non-zero exit, message on
  stderr), not silently swallowed.

### `build_shipped_table.py`
Run on demand (`python3 scripts/instrumentation/build_shipped_table.py`,
takes roughly a minute or two — it scans every merged PR into `develop`).
Makes **zero writes to bd**; makes network calls via the `gh` CLI, which is
allowed here specifically because this is the one designated batch job, not
a hook. Produces `out/shipped_issues.csv` and `out/shipped_issues.db`
(SQLite table `shipped_issues`), both gitignored and fully regenerated on
every run — one row per bd issue closed on or after epoch zero
(2026-07-26):

```
issue_id, type, claimed_at, first_commit_at, pr_opened_at, merged_at,
deployed_at, active_seconds, session_count, reviewer_iterations,
files_changed, lines_changed, size_estimate_at_claim, developer_model,
reviewer_model, tooling_version, escaped
```

Where each field comes from:

- `claimed_at`, `type` — bd (`bd list --status=closed --json`, read-only).
- `first_commit_at`, `pr_opened_at`, `merged_at`, `files_changed`,
  `lines_changed` — the GitHub PR that has a commit carrying
  `Bead: <issue_id>`. **Not** sourced from `git log` on `develop`/`main`:
  this repo squash-merges feature PRs, and a squash commit's message is the
  PR title + description, not the original commits — verified empirically
  against a real merged PR (#216) before writing this, and the `Bead:`
  trailer does not survive the squash. What does survive: `GET
  /repos/{owner}/{repo}/pulls/{number}/commits` keeps returning a merged
  PR's original pre-squash commits (full message, trailer included)
  indefinitely, even after the source branch is deleted — also verified
  live against this repo. So the join enumerates merged PRs and matches on
  their original commits, not on `develop`'s own history.
- `deployed_at` — specifically the **production** deploy, not staging.
  A PR's squash commit lands on `develop` directly; it only reaches `main`
  once some later `develop`→`main` promotion PR (a real merge commit, per
  `docs/git-hygiene.md`) carries it over. This script walks `main`'s merge
  commits to find the first one with the issue's squash commit as an
  ancestor (`git merge-base --is-ancestor`), then reads that promotion
  commit's `deploy-prod.yml` run, specifically the `"Deploy to production
  Droplet"` job's `completed_at` (verified live against this repo's
  GitHub Actions in Phase 0 — that job name and field are real, not
  assumed). If the squash commit hasn't reached `main` yet, `null`.
- `active_seconds`, `session_count` — `sessions.jsonl` / `agents.jsonl`,
  joined to an issue by parsing `git_branch` back into a `<type>/<id>-<slug>`
  issue id (the same convention `bead-start.sh` creates). A session whose
  branch doesn't match that shape contributes to no issue's totals.
  Distinguishes "not measured" (`null` — the collector wasn't live yet when
  this issue shipped) from "measured, genuinely zero" (`0`/`null` durations
  — the collector was live, but no session ever ran on a matching branch)
  using the earliest timestamp actually present in `sessions.jsonl` itself
  as the "collector went live" marker. Right now, for every currently-closed
  issue, this is `null` — the collector didn't exist yet when any of them
  shipped. That's correct, not a bug.
- `reviewer_iterations` — same not-measured-vs-zero logic, against
  `reviews.jsonl`.
- `size_estimate_at_claim` — **always `null`**. bd has an `estimated_minutes`
  column, but it's unused in this project (0 of 281 issues have it set as
  of 2026-07-29) — nothing to snapshot at claim time.
- `developer_model`, `reviewer_model` — **always `null`**, per the "What
  this cannot measure" section below.
- `tooling_version` — **always `null`**. No stored raw event anywhere
  captures which bd or Claude Code version was active for a given piece of
  work; inventing a value from "whatever version is installed today" would
  misrepresent history, so this stays unpopulated rather than misleading.
- `escaped` — **always `null`**. Would need a caused-by/discovered-from
  dependency edge type in bd to derive "this shipped fix later caused a
  production bug"; no such edge type exists in this bd install (confirmed
  in Phase 0, and previously during the unrelated `bd_velocity_analysis.py`
  work — only `parent-child` and `blocks` exist).

### `log_intervention.py`
Appends to `.instrumentation/interventions.jsonl` — the one file under
`.instrumentation/` that **is** committed, since it's meant to be read as
part of the repo's own history, not regenerated:

```
scripts/instrumentation/log_intervention.py \
    --date 2026-07-26 \
    --change "one sentence describing what changed" \
    --expected-effect "what you expect to happen, written before the change lands" \
    --segment claimed_at_to_first_commit_at   # or one of the other shipped_issues.csv segments, or "other"
```

`--expected-effect` is a required, non-empty argument — there's no
technical way for a script to enforce "written before the change lands,"
but requiring the field up front at least removes the easy way to skip
stating it, or to write it retroactively once you've already seen the data.

Seeded with two entries so far, both dated 2026-07-26: adopting bd itself
(expected effect: the whole join key becomes measurable at all, not
necessarily faster or slower), and `MysteryMixClub-s7bv2t`/MYS-259 moving
the frontend build off the prod droplet into CI and switching to a graceful
gunicorn reload (expected effect: `merged_at_to_deployed_at` should shrink
and stop occasionally spiking, since the on-droplet build no longer
competes with the running app for a 2GB box's resources). I looked for a
dated model-assignment change to seed as a third entry, per the original
ask — found none in version control (no agent `.md` file's `model:`
frontmatter has ever changed in this repo's git history) — rather than
invent one, this is left for whoever actually makes that change to log
going forward.

## Schema versions

Every JSONL record carries `schema_version` (currently `1` everywhere). Bump
it, don't mutate old records in place, if a field's meaning ever changes —
the whole point of append-only logs is that old lines stay exactly what
they said at the time.

## What this still cannot measure

**Per-subagent model and token attribution does not exist anywhere in this
project today**, not just in this collector. Hook payloads confirmed don't
carry it. The separate OTel/Prometheus pipeline from `MysteryMixClub-ysu2`
(already running on this machine) does carry a `model` label, but its
`agent_name` label is hardcoded to the literal string `"custom"` for every
data point — it was never actually wired to break out by subagent despite
that being ysu2's own acceptance criterion. So `developer_model` and
`reviewer_model` — both wanted by the Phase 4 shipped-issue table — will be
`null` until one of two things happens: the OTel `agent_name` tagging gets
fixed (a separate, not-yet-filed piece of work), or an offline
transcript-parser is built against `~/.claude/projects/*/*.jsonl` (viable,
per Dawn's own precedent in ysu2's scope note that this format is
internal-and-shifting, so it must stay a one-off/offline tool, never a
standing pipeline, and never inline in a hook).

Everything else this collector produces is a genuine measurement, not an
estimate — but it only covers work from 2026-07-26 forward. There is no
retroactive fix for that; the whole point of an event collector is that it
can't see events from before it existed.
