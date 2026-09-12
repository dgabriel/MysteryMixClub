---
name: mmc-git-hygiene
description: Apply MysteryMixClub git policy when starting a branch, preparing commits or pull requests, syncing code branches, resolving merge conflicts, or recovering git history.
---

# MysteryMixClub Git Hygiene

Read [the canonical git policy](../../../docs/git-hygiene.md) before git work.
Resolve repository paths from the root containing `AGENTS.md`. Keep detailed
rules and recovery procedures in that document rather than copying them here.

For issue work, use [the issue-start script](../../../scripts/bead-start.sh)
as required by `AGENTS.md`; consult the `mmc-issue-management` skill for issue
operations. Git policy remains in `docs/git-hygiene.md` if older issue guidance
disagrees about branching or merging.

Select the document sections relevant to the operation:

- Branch setup or synchronization: Golden Rules and Working Tree.
- Commits or pushes: Commits and Pre-flight before pushing.
- PRs or conflicts: Pull Requests, including the reconciliation gate.
- Recovery: the specific recovery procedure and Working Tree safeguards.

Apply the user's current scope and authorization. Loading this skill does not
authorize commits, pushes, merges, remote issue sync, or destructive cleanup.
Explicit user instructions take precedence over skill guidance. At handoff,
report the branch, changed files, validation, and any remaining git actions.
