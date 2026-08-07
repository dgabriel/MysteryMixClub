# Git Hygiene — Non-Negotiable

Read this at the start of **every** task that may touch git. The goal is a clean,
legible history and a working tree that is never in a "weird state." When in doubt,
stop and ask — do not improvise your way out of a git mess.

Related: branch model in `docs/ci-cd.md`. Hook PATH gotcha at the bottom of this file.

---

## The Golden Rules

1. **Know where you are before you do anything.** Run `git status` and
   `git branch --show-current` before you start and before every commit. Never
   assume the branch or the working-tree state.
2. **Never commit directly to `main` or `develop`.** All work happens on a
   `feature/*` (or `fix/*`) branch and reaches them only through a PR. `main` =
   production, `develop` = staging.
3. **Every branch is based off `develop` — no exceptions.** Cut every `feature/*`
   or `fix/*` branch from an **up-to-date** `develop`. Never branch off `main`,
   and never branch off another feature branch (stacked branches drift and are
   how merges silently drop code). Always pull first so you start from the latest:
   ```
   git checkout develop && git pull --ff-only origin develop
   git checkout -b feature/MysteryMixClub-<bd-id>-short-slug
   ```
   (`scripts/bead-start.sh <bd-id>` does exactly this — sync, branch, claim —
   in one step; use it instead of the manual sequence above when starting
   work on a bd issue.)
   If a branch ends up based on anything other than current `develop`, rebase it
   onto `develop` before continuing (`git rebase origin/develop`).
   **Create the branch before writing a single line of code.** Never edit files
   on `develop` and branch after — you will end up with uncommitted changes on a
   shared branch. Branch first, then code.
   **Start from origin state, not local state.** Dawn sometimes merges PRs from
   the GitHub web UI. Before trusting any local branch, always:
   ```
   git fetch --prune
   ```
   Then prune local branches whose upstream is gone (`git branch -vv | grep
   ': gone]'`) — each one either merged already (safe to delete) or needs a
   look before deleting, never silently kept around as if still live.

   **`develop` is a protected branch (since 2026-08-07).** The repo sets
   `delete_branch_on_merge: true`, and a promotion PR's head branch *is*
   `develop` — so until this protection existed, **every** `develop → main`
   promotion deleted `origin/develop`, leaving your local copy looking fine
   while its upstream was silently gone. That was the expected outcome of a
   normal promotion, not a rare accident. Branch protection stops it, because
   GitHub does not auto-delete a protected branch:

   - `allow_deletions: false` — the setting that actually stops the auto-delete
   - `allow_force_pushes: false`
   - Require a PR before merging: on, with 0 required approvals
   - Required status checks: none configured (green CI is still the merge gate
     in practice — see Pull Requests below)
   - `enforce_admins: false` — Dawn can still bypass deliberately

   Do not remove this protection to work around an awkward merge. If
   `origin/develop` goes missing anyway, recover — don't improvise:

   - **Local `develop` still exists** (the normal case) — fast-forward it to
     `main` and push it back. Prove containment first: if the promotion was a
     real merge commit, local `develop` is an ancestor of `main`, so the
     fast-forward loses nothing.
     ```
     git merge-base --is-ancestor develop origin/main   # must succeed first
     git checkout develop && git merge --ff-only origin/main
     git push -u origin develop
     ```
     If that `--is-ancestor` check fails, stop — `develop` has commits `main`
     never absorbed, and fast-forwarding would strand them.
   - **No local `develop` either** — only then create it from `main`:
     ```
     git checkout main && git pull --ff-only origin main
     git checkout -b develop && git push -u origin develop
     ```

   If `origin/develop` does exist but your local one doesn't (or is stale),
   just track/reset to it — don't recreate it from `main`, that would discard
   anything on `origin/develop` that `main` hasn't absorbed yet.
4. **One branch at a time.** Finish and merge the current branch before starting
   the next piece of work. Do not begin new feature code while a PR is open and
   unmerged — even if asked. Stack depth = 1.
5. **bd issues and git branches are separate axes — don't conflate them.** Since
   the 2026-07-26 move off Linear, issue state lives in bd's own Dolt store,
   synced via `refs/dolt/data` — a ref namespace alongside but independent of
   `refs/heads/*`. Checking out a different git branch does not change which bd
   issues exist or their status; nothing about this branch model needs to change
   because of bd.
   - **Don't adopt bd's own Dolt-native branching** (`bd branch`) as a
     per-feature-branch mirror of git branches. It's available, but at this
     project's scale (one primary developer plus occasional collaborators, not
     concurrent teams needing isolated issue-state experiments) it only adds a
     second merge-conflict surface for no payoff. One shared bd history is enough.
   - **Sequence `bd dolt push` after the PR merges and the issue closes, not
     before.** Issue state and code state sync independently, so pushing dolt
     state ahead of the actual merge would let a collaborator pull a "closed"
     issue whose code isn't in `develop` yet. This is already how the session-close
     protocol is wired (see the Beads section of `CLAUDE.md` and the
     `mmc-issue-management` skill) — just don't run `bd dolt push` manually out
     of that order.
6. **Never force-push a shared branch** (`main`, `develop`, or any branch with an
   open PR / other readers). `--force-with-lease` only ever on your own private
   feature branch, and only when you understand why.
7. **Never rewrite published history.** Don't `rebase`, `amend`, or `reset` commits
   that have already been pushed to a shared branch. Amend only local, unpushed
   commits.
8. **Don't fast-forward `main` to `develop`.** The gap is intentional (un-promoted
   staging work).
9. **Don't cherry-pick app/tooling changes into `main`.** They reach prod only via
   a deliberate `develop → main` promotion PR. Beta went live 2026-07-25 — the old
   pre-beta rule limiting promotions to README-only is retired; `main` and `develop`
   are now kept nearly in sync via routine full promotion PRs (app code, docs,
   tooling, all of it), same merge-commit-only mechanics as any other promotion.

---

## Commits

- **One logical change per commit.** No "misc fixes" grab-bags; no unrelated files
  riding along. Check `git diff --staged` before committing.
- **Conventional Commits**, enforced by commitlint: `type(scope): subject`
  (`feat`, `fix`, `chore`, `docs`, `refactor`, `test`, …). Imperative subject,
  no trailing period.
- **End commit messages with the Claude co-author trailer**, naming whichever
  model is actually running the session — e.g.:
  ```
  Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
  ```
  Don't pin a specific model name here as a hardcoded example to copy
  verbatim; it'll go stale the next time the underlying model changes.
- **Only commit/push when the user asks** (or under a standing autonomy grant
  explicitly given for that scope of work). Flag risky changes even then.
- **Stage intentionally.** Prefer naming paths over `git add -A`. Never commit
  secrets, `.env`, build artifacts, or scratch files — check `git status` first.
- **Never use `git commit --no-verify`** to skip hooks. If a hook fails, fix the
  cause. If the hook itself is broken, see the PATH note below.

---

## Working Tree — staying out of weird states

- **Keep the tree clean.** Don't start new work on top of unrelated uncommitted
  changes. Commit, stash, or discard first — deliberately.
- **`git stash` is not a parking lot.** If you stash, pop it back in the same
  session; a forgotten stash is a future "where did my change go."
- **Never leave a detached HEAD.** If `git status` says "HEAD detached," stop and
  get back onto a named branch before doing anything else.
- **Resolve conflicts, never paper over them.** During a merge/rebase conflict,
  resolve every marker, re-run the relevant tests, then continue. If it's beyond
  a clean resolution, `git merge --abort` / `git rebase --abort` and reassess —
  do not force a half-merged tree.
- **Destructive commands need confirmation.** `git reset --hard`, `git clean -fd`,
  branch deletion, and force-push can lose work irrecoverably. State what will be
  lost and confirm before running them.
- **Recover, don't panic.** `git reflog` finds "lost" commits after a bad
  reset/rebase. Reach for it before recreating work.

---

## Pull Requests

- Feature branch → PR into `develop`; CI (`ruff · mypy · pytest` + frontend
  typecheck) must be green before merge.
- `develop → main` is a separate, deliberate promotion PR with a manual approval
  gate (deploys to prod). **Always merge it with "Create a merge commit" — never
  squash, never rebase.** A GitHub ruleset on `main` enforces this (merge-only;
  `develop` is untouched and still squash-friendly for feature PRs). See "Why
  promotions must be a real merge" below for what happens if this is skipped.
- **Always target `develop`** when creating a PR. Pass `--base develop` explicitly
  (`gh pr create --base develop …`) — never let the CLI default to `main`.
- Keep the branch current with `git pull --rebase` (your own branch) or a merge
  from `develop`; don't let it drift far behind.
- **Feature/fix → `develop`: green CI is enough to merge.** Staging (what
  `develop` deploys to) has no real users anymore — only testers — since the
  app went live in prod. Once `ruff · mypy · pytest` + frontend typecheck all
  pass, merge; no manual end-to-end smoke test or explicit go-ahead is
  required first. This does **not** extend to `develop → main`: that
  promotion is a real prod deploy, and only Dawn merges it, regardless of CI
  status — never Claude, even with everything green.
- **Merge promptly.** Once CI is green, merge immediately. Open PRs drift from
  `develop` and compound conflict risk for every other branch in flight.

### Merging without losing code (the squash-merge trap)

Hand-resolving a squash-merge conflict has silently dropped feature code into the
void more than once. A squash collapses a branch to a single new commit, so any
hunk you fail to carry over leaves **no trace** in `develop`'s history — the
branch looks merged, the code is gone. Rules:

1. **Never hand-resolve a squash conflict.** If `gh pr merge --squash` reports a
   conflict, stop. Rebase the feature branch onto the latest `develop` first
   (`git rebase origin/develop`, resolve there with full context), push, and let
   the squash apply cleanly with zero manual resolution at merge time.
2. **Mandatory post-merge reconciliation gate.** Before deleting any branch,
   prove nothing was lost:
   ```
   git diff <feature-branch> origin/develop -- <each changed file>
   ```
   The only remaining differences may be the squash's own collapsing — every
   functional line the branch added must be present in `develop`. If anything is
   missing, the merge ate it: recover from the branch (still un-deleted) before
   doing anything else. Do **not** delete the branch until this diff is clean.
3. **Recover, don't recreate.** A "lost" feature is almost always still reachable
   via `git log --all` / `git reflog` on its original branch. Port the missing
   hunks forward; never rewrite the feature from scratch.

### Why promotions must be a real merge

On 2026-07-25, two `develop → main` promotion PRs (#175, #182) were squash-merged.
A squash collapses the source branch's commits into one flattened commit on the
target — so `main` never recorded those `develop` commits as ancestors. `git
merge-base main develop` stayed pinned at the point *before* the first-ever
promotion, months earlier.

The practical effect: the next promotion PR showed conflicts in files that had
been touched again on `develop` after the squash (MYS-239's form-validation
rework), even though there was no real disagreement — `main`'s side was just
stale pre-MYS-239 code sitting at the wrong point in git's history. Fixed by a
one-time real merge of `main` into `develop` (restoring the ancestor link) before
the next promotion could go through cleanly. Full incident + diagnosis in the
PR that fixed it (`chore/heal-main-develop-history`).

**A squash or rebase merge into `main` will silently reintroduce this** — the
next promotion after it will show phantom conflicts again, for the same
structural reason. This is why the merge method is enforced by a GitHub ruleset
on `main` (`allowed_merge_methods: ["merge"]`), not just this doc — don't work
around it by merging outside `gh pr merge`; if a promotion PR is not
fast-forwardable and `gh pr merge --merge` refuses, stop and reconcile the
history first (see above), don't reach for `--squash` as the fast way out.

---

## Pre-flight before pushing (catch CI failures locally)

- Pre-push runs frontend typecheck, `mypy`, and `pytest` in that order; let
  it. Don't bypass. (Before 2026-07-31, `mypy` was CI-only and had to be run
  by hand pre-push — the hook now covers it, closing that gap.)
- **Hook PATH gotcha — fixed 2026-07-26.** The hooks (`.beads/hooks/pre-commit`,
  `.beads/hooks/pre-push`, and the `.husky/*` originals kept in sync) now export
  `backend/.venv/bin` onto `PATH` themselves before calling `ruff`/`pytest`, so
  they resolve the right interpreter regardless of what a given shell finds
  first (e.g. Anaconda). No manual `PATH=...` prefix needed anymore — if you see
  ENOENT / ModuleNotFoundError from a hook, that's a real regression, not this
  old gotcha; investigate rather than reaching for the workaround.
- Pushes to `main`/`develop` share one Postgres test DB serially — **never run two
  pushes concurrently** or pre-push deadlocks.
