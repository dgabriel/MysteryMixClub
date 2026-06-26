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
3. **Branch off the right base.** Cut feature branches from an up-to-date
   `develop`, never from `main`:
   ```
   git checkout develop && git pull --ff-only origin develop
   git checkout -b feature/mys-XX-short-slug
   ```
4. **Never force-push a shared branch** (`main`, `develop`, or any branch with an
   open PR / other readers). `--force-with-lease` only ever on your own private
   feature branch, and only when you understand why.
5. **Never rewrite published history.** Don't `rebase`, `amend`, or `reset` commits
   that have already been pushed to a shared branch. Amend only local, unpushed
   commits.
6. **Don't fast-forward `main` to `develop`.** The gap is intentional (un-promoted
   staging work). See [[project_branch-topology]].
7. **Don't cherry-pick app/tooling changes into `main`.** They reach prod only via
   a deliberate `develop → main` promotion PR. Until the official beta, the only
   thing promoted to `main` is README docs (preserve main's pre-launch banner).

---

## Commits

- **One logical change per commit.** No "misc fixes" grab-bags; no unrelated files
  riding along. Check `git diff --staged` before committing.
- **Conventional Commits**, enforced by commitlint: `type(scope): subject`
  (`feat`, `fix`, `chore`, `docs`, `refactor`, `test`, …). Imperative subject,
  no trailing period.
- **End commit messages with the Claude co-author trailer:**
  ```
  Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
  ```
- **Only commit/push when the user asks** (or under a standing autonomy grant —
  see [[feedback-commit-autonomy]]). Flag risky changes even then.
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
  gate (deploys to prod).
- Keep the branch current with `git pull --rebase` (your own branch) or a merge
  from `develop`; don't let it drift far behind.

---

## Pre-flight before pushing (catch CI failures locally)

- **Run `mypy` yourself** — it is **not** in the pre-push hook, only in CI.
  See [[project_mypy-not-in-prepush]]. `cd backend && mypy app`.
- Pre-push runs `pytest`; let it. Don't bypass.
- **Hook PATH gotcha:** Husky hooks call `ruff`/`pytest` by bare name but they
  live in `backend/.venv/bin`. Prefix the git command or the hook fails with
  ENOENT / ModuleNotFoundError:
  ```
  PATH="$PWD/backend/.venv/bin:$PATH" git push origin <branch>
  ```
  See [[project_git-hooks-venv]].
- Pushes to `main`/`develop` share one Postgres test DB serially — **never run two
  pushes concurrently** or pre-push deadlocks.
