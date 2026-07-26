---
name: mmc-issue-management
description: MysteryMixClub-specific issue tracking workflow with bd (beads), the sole issue tracker as of 2026-07-26 (Linear is retired/read-only). Use whenever creating, claiming, updating, closing, or branching off an issue in this repo, or when reconciling old MYS-## references against the current bd database.
---

# MysteryMixClub Issue Management (bd / beads)

Linear is retired for this project. **bd is the only place issues get created, claimed, or closed going forward.** This skill layers MysteryMixClub's project-specific rules on top of beads' own opinionated defaults (see the generic `beads` skill / `bd prime` for the vanilla CLI reference) — read this one for the parts that are specific to *this* repo.

## The migration, in one paragraph

On 2026-07-26 all 259 Linear issues (team `MYS`) were pulled into bd via `bd linear sync --pull`. **bd's local issue IDs are hashes, not `MYS-##`** — e.g. `MysteryMixClub-s7bv2t`, not `MYS-259`. Each imported issue keeps the original Linear URL (with its `MYS-##` number) in the `external_ref` field purely for historical continuity — it is not a live link and nothing writes back to Linear anymore. When a person references an old `MYS-##` number, resolve it with `bd search` on the title, or `bd list --json` and grep `external_ref`, not by guessing the bd ID. New issues created from here on never get a `MYS-##` — don't invent one.

## Non-negotiables (from bd's own design, applies here without modification)

- **bd is the single tracker.** Do not use TodoWrite, TaskCreate, or markdown TODO files for anything that should survive past this conversation turn. (Those tools are still fine for a single turn's own execution checklist — see [[project_agent-workflow]]-style role separation below.)
- **Priorities are `0`-`4`** (0 = critical, 4 = backlog), never "high"/"medium"/"low".
- **Never run `bd edit`** — it opens `$EDITOR` and blocks the agent. Use `bd update <id> --title/--description/--notes/--design` instead.
- **Claim before working:** `bd update <id> --claim`. **Close when actually done:** `bd close <id> --reason="..."`. Don't auto-close speculative or partially-done work.
- Session close protocol (from `bd prime`): close finished issues → run quality gates → `git status` → follow the active git profile (below) → hand off with a summary. Do this before saying "done."

## What's specific to MysteryMixClub

**Branch naming.** Keep the human-readable number when one exists: if the issue's `external_ref` has a `MYS-##`, branch as `feature/mys-##-slug` for continuity with existing history/PRs. For issues created natively in bd (no `MYS-##`), use a short slug of the bd id or title: `feature/s7bv2t-slug` or `feature/prod-multiworker-api`. Either way — per [[feedback_branch-before-code]] — create and switch to that branch **before the first Read/Edit/Write of the task**, off a freshly-fetched `develop`:
```
git fetch --prune && git checkout develop && git pull --ff-only origin develop
git checkout -b feature/<slug>
```

**One branch at a time, sync first, merge immediately.** These are unchanged by the bd migration:
- [[feedback_one-branch-at-a-time]]: don't start new bd-tracked work until the current branch is squash-merged and deleted.
- [[feedback_sync-before-actions]]: `git fetch --prune` before any branch/PR/cleanup action — stale remote-tracking refs cause phantom "orphan branch" diagnoses.
- [[feedback_merge-immediately]]: once a PR is green, merge it — `gh pr create --base develop` (never default `main`), then `gh pr merge <N> --squash --delete-branch`, then `bd close <id>`. Don't leave PRs open.
- [[feedback_squash-merge-data-loss]]: never hand-resolve a squash conflict — rebase onto `origin/develop` first. Before deleting any branch, diff it against `origin/develop` per changed file to confirm nothing was dropped.

**Manual test before merge, with the same narrow exceptions as before.** [[feedback_manual-test-before-merge]]: pause after opening the PR, give a short manual-test checklist, wait for a go-ahead — do not merge on green CI alone. [[feedback_commit-autonomy]] and [[feedback_merge-autonomy-compliance-batch]] show the only shape an exception takes: a **narrow, explicitly-granted, ticket-scoped** waiver (e.g. "for MYS-9/10 only" or "for this docs-only batch only"). A general "we're moving to bd" instruction is not that grant — treat every PR as needing the manual-test pause unless the user names the specific issue(s) exempted, in this conversation.

**Targeted test runs.** [[feedback_targeted-test-runs]] still applies: run only the relevant backend test file(s) during iteration, the full suite only pre-push/pre-PR (the pre-push hook already runs it). Never run backend tests for a frontend-only bd issue.

**Git hygiene doc is still canonical.** Read `docs/git-hygiene.md` before any branch/commit/push/merge/rebase, per [[feedback_git-hygiene]] — bd changes *what* you track, not the underlying git rules.

**Agent role separation still applies.** [[feedback_agent-workflow]]: when work tracked in bd runs through the developer/tester/reviewer/ui-agent subagents, keep those roles separate — a bd issue moving through the pipeline is not a reason to collapse review into the main thread.

**Local ticket log habit is retired.** [[feedback_local-ticket-log]] (maintain a gitignored `TICKETS.md`, only round-trip to Linear when told) is now obsolete — bd's local Dolt DB *is* the fast local reference that habit was trying to approximate, with no round-trip needed because there's no longer a remote source of truth to protect from over-querying. Query bd directly (`bd ready`, `bd list`, `bd show <id>`) instead of maintaining a parallel file.

## Git/sync authority — pull is routine, push still needs authority

`bd dolt pull` and `bd dolt push` are not symmetric — treat them differently:
- **`bd dolt pull` is wired into session start** (`CLAUDE.md` → "On Every Session Start" step 2) and safe to run unconditionally, every session, without asking — it only merges remote issue state into the local DB, no git branches or shared state touched.
- **`bd dolt push` still requires explicit authority for that specific action**, per the Agent Context Profiles in the bd-managed `CLAUDE.md` block (Conservative default: report and wait; Team-maintainer: push as part of session close). A general "switch to bd" or "wire in sync" instruction is not blanket authorization for every future push — it's already wired into the Team-maintainer session-close protocol, but Conservative sessions still need a per-instance go-ahead.
- The full migration (259 issues, doc/skill updates, the hooks fix) is already pushed as of 2026-07-26 — `refs/dolt/data` exists on `origin`, confirmed via `git ls-remote`. This is the steady state to keep it in; don't assume a fresh `bd dolt push` is needed unless local issues have changed since the last one.
- `core.hooksPath` points at `.beads/hooks` instead of `.husky/_` (a side effect of `bd init`). This is a **local, per-clone git config** — it is not tracked in git and does not propagate from a commit. Anyone else working in this repo needs to run `bd hooks install` themselves once. The existing Husky commands (`lint-staged`, `commitlint`, `typecheck`, `pytest`) were preserved inline in the hook scripts, not dropped — verify with `bd hooks list` if in doubt. Both `.beads/hooks/*` and `.husky/*` now export the backend venv onto `PATH` before calling `ruff`/`pytest`, so those tools resolve correctly regardless of which Python a given shell finds first.

## Known open tension: `bd remember` vs. the personal memory system

bd's own guidance (and the managed CLAUDE.md block) says to use `bd remember` / `bd memories` for persistent knowledge and explicitly *not* use `MEMORY.md` files, on the grounds that they fragment across accounts. This conflicts with Claude Code's separate cross-project auto-memory system (the one indexed by `~/.claude/projects/.../memory/MEMORY.md`), which is already the durable home for `user`/`feedback`/`project`/`reference` memories across every project, MysteryMixClub included — and which this skill itself was written from.

Don't silently pick a side. Until Dawn decides otherwise:
- Keep using the personal auto-memory system for cross-project knowledge — user preferences, workflow feedback, reference pointers — exactly as before. It is not beads' concern and beads has no visibility into it.
- Use `bd remember` only for knowledge that should live *inside this repo's bd database* and travel with it — context another clone or a CI worker running bare `bd` (with no access to this personal memory store) would need. Project facts that are really about the codebase/infra (e.g. "staging is a Droplet at this IP") arguably belong here going forward, not just in personal memory — but don't duplicate wholesale; migrate a memory into `bd remember` only when something bd-native will actually consume it.
- If this split starts causing real confusion (the same fact drifting out of sync in both places), flag it back to Dawn rather than guessing further.
