#!/usr/bin/env python3
"""Phase 4 batch enrichment: one row per shipped bd issue.

Run on demand:
    python3 scripts/instrumentation/build_shipped_table.py

Makes ZERO writes to bd -- every bd call is `bd show`/`bd list` (read-only).
Makes network calls via the `gh` CLI (already authenticated) -- this is the
one place in the whole instrumentation design allowed to do that; hooks
(scripts/instrumentation/hooks/*.py) never call the network.

Epoch zero is 2026-07-26 (UTC midnight). Only bd issues closed on or after
that date are included -- nothing earlier is backfilled, because the whole
join mechanism (Bead: trailers, bd's own claim timestamps, the event
collector) didn't exist before then and there is nothing honest to compute
for older issues.

Output: scripts/instrumentation/out/shipped_issues.csv and
scripts/instrumentation/out/shipped_issues.db (SQLite). Both gitignored,
regenerated in full on every run (this script doesn't do incremental
updates -- see README for why that's a deliberate simplicity choice, not an
oversight).

## Why the git join is via the GitHub PR commits API, not `git log`

This repo squash-merges feature PRs into `develop` (confirmed live,
docs/git-hygiene.md, docs/ci-cd.md). A squash-merge commit's message on
`develop` is the PR title + description -- it does NOT retain individual
commits' `Bead:` trailers (verified empirically against real merged PRs in
this repo, e.g. PR #216, before writing this script). So `git log --grep`
against `develop`/`main` cannot find the join key.

What DOES retain it: `GET /repos/{owner}/{repo}/pulls/{number}/commits`
keeps returning a merged PR's original, pre-squash commits (full message,
including any trailer) indefinitely, even after the source branch is
deleted -- verified against this repo's own history. So the join here is:
enumerate merged PRs -> pull each one's original commits -> match on a
`Bead: <id>` line in any commit's full message.

## Deploy timestamp

Verified live against this repo's GitHub Actions (Phase 0): a workflow
run's job named "Deploy to staging Droplet" / "Deploy to production
Droplet" has a `completed_at` field, which is the actual moment the deploy
script finished running on the target Droplet.

"Shipped" here means reached **production**, not just staging. A
squash-merge onto `develop` produces one new commit (`merge_commit_sha` on
the PR); that sha becomes an ancestor of `main` only once some later
develop->main promotion PR (a real merge commit, not squash, per
git-hygiene.md) carries it over. So: walk main's merge commits looking for
the first one that has this issue's squash commit as an ancestor, then find
the deploy-prod.yml run whose head_sha is that promotion commit, then read
its "Deploy to production Droplet" job's completed_at. If the squash commit
hasn't reached main yet, deployed_at is null -- not "pending", not "0",
null, because there is no event yet to derive it from.
"""
from __future__ import annotations

import csv
import json
import re
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent / "hooks"))
from _common import instrumentation_dir  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = Path(__file__).resolve().parent / "out"
OUT_DIR.mkdir(parents=True, exist_ok=True)

EPOCH_ZERO = datetime(2026, 7, 26, 0, 0, 0, tzinfo=timezone.utc)
BEAD_TRAILER_RE = re.compile(r"^Bead:\s*(\S+)\s*$", re.MULTILINE)
BRANCH_ID_RE = None  # set once we know the bd prefix, see _branch_id_regex()


def _run(cmd: list[str], cwd: Path = REPO_ROOT, timeout: int = 30) -> str:
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError(f"command failed ({r.returncode}): {' '.join(cmd)}\n{r.stderr}")
    return r.stdout


def _run_ok(cmd: list[str], cwd: Path = REPO_ROOT, timeout: int = 30) -> tuple[bool, str]:
    """Like _run but never raises -- returns (success, stdout)."""
    try:
        r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
        return r.returncode == 0, r.stdout
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)


def _parse_dt(s: str | None) -> datetime | None:
    if not s:
        return None
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def gh_json(args: list[str]) -> Any:
    ok, out = _run_ok(["gh"] + args)
    if not ok or not out.strip():
        return None
    try:
        return json.loads(out)
    except json.JSONDecodeError:
        return None


# ---------------------------------------------------------------------------
# bd (read-only)
# ---------------------------------------------------------------------------
def bd_prefix() -> str:
    out = json.loads(_run(["bd", "where", "--json"]))
    return out["prefix"]


def bd_closed_issues_since(epoch: datetime) -> list[dict]:
    raw = json.loads(_run(["bd", "list", "--status=closed", "--json", "--all", "--limit", "0"]))
    result = []
    for issue in raw:
        closed_at = _parse_dt(issue.get("closed_at"))
        if closed_at is not None and closed_at >= epoch:
            result.append(issue)
    return result


# ---------------------------------------------------------------------------
# GitHub (read-only, network -- only ever called from this batch script)
# ---------------------------------------------------------------------------
def repo_nwo() -> str:
    return json.loads(_run(["gh", "repo", "view", "--json", "nameWithOwner"]))["nameWithOwner"]


def list_merged_prs(nwo: str, base: str) -> list[dict]:
    prs = gh_json(
        [
            "pr", "list", "--repo", nwo, "--state", "merged", "--base", base,
            "--limit", "1000",
            "--json", "number,createdAt,mergedAt,mergeCommit,headRefName",
        ]
    )
    return prs or []


def pr_commits(nwo: str, number: int) -> list[dict]:
    out = gh_json(["api", f"repos/{nwo}/pulls/{number}/commits"])
    return out or []


def pr_details(nwo: str, number: int) -> dict | None:
    return gh_json(["api", f"repos/{nwo}/pulls/{number}"])


def workflow_run_job(nwo: str, workflow_file: str, head_sha: str, job_name: str) -> dict | None:
    """Find the named job's record for the workflow run matching head_sha."""
    runs = gh_json(["api", f"repos/{nwo}/actions/workflows/{workflow_file}/runs", "--paginate"])
    if not runs:
        return None
    all_runs = runs.get("workflow_runs", []) if isinstance(runs, dict) else []
    for run in all_runs:
        if run.get("head_sha") == head_sha:
            jobs = gh_json(["api", f"repos/{nwo}/actions/runs/{run['id']}/jobs"])
            if not jobs:
                continue
            for job in jobs.get("jobs", []):
                if job.get("name") == job_name:
                    return job
    return None


# ---------------------------------------------------------------------------
# Join: bd issue -> merged PR, via the Bead trailer on original PR commits
# ---------------------------------------------------------------------------
def find_matching_pr(issue_id: str, prs_with_commits: list[dict]) -> dict | None:
    for pr in prs_with_commits:
        matching_commits = [
            c for c in pr["_commits"]
            if issue_id in BEAD_TRAILER_RE.findall(c.get("commit", {}).get("message", ""))
        ]
        if matching_commits:
            first_commit_at = min(
                _parse_dt(c["commit"]["author"]["date"]) for c in matching_commits
            )
            return {"pr": pr, "first_commit_at": first_commit_at}
    return None


def find_deployed_at(nwo: str, squash_sha: str, main_merge_commits: list[str]) -> datetime | None:
    promotion_sha = None
    for msha in main_merge_commits:  # oldest first
        ok, _ = _run_ok(["git", "merge-base", "--is-ancestor", squash_sha, msha])
        if ok:
            promotion_sha = msha
            break
    if promotion_sha is None:
        return None  # not yet promoted to main
    job = workflow_run_job(nwo, "deploy-prod.yml", promotion_sha, "Deploy to production Droplet")
    if not job or not job.get("completed_at"):
        return None
    return _parse_dt(job["completed_at"])


# ---------------------------------------------------------------------------
# Instrumentation-log join: sessions.jsonl / agents.jsonl / reviews.jsonl
# ---------------------------------------------------------------------------
def load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    records = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return records


def branch_issue_id(branch: str | None, prefix: str) -> str | None:
    if not branch:
        return None
    m = re.match(rf"^(?:feature|fix)/({re.escape(prefix)}-[A-Za-z0-9]+(?:\.[0-9]+)?)-", branch)
    return m.group(1) if m else None


def build_session_agent_index(prefix: str) -> tuple[dict[str, list[str]], dict[str, list[int]], datetime | None]:
    """Returns (issue_id -> [session_id,...], issue_id -> [duration_ms,...], collector_live_since).

    collector_live_since is the earliest ts in sessions.jsonl, or None if the
    log has never been written to -- used to distinguish "not measured yet"
    (null) from "measured, genuinely zero" (0) per issue.
    """
    events_dir = instrumentation_dir(str(REPO_ROOT)) / "events"
    sessions = load_jsonl(events_dir / "sessions.jsonl")
    agents = load_jsonl(events_dir / "agents.jsonl")

    collector_live_since = None
    if sessions:
        collector_live_since = min(_parse_dt(s["ts"]) for s in sessions if s.get("ts"))

    session_branch: dict[str, str] = {}
    for s in sessions:
        if s.get("event_type") == "SessionStart" and s.get("session_id"):
            session_branch[s["session_id"]] = s.get("git_branch")

    issue_sessions: dict[str, set[str]] = {}
    for sid, branch in session_branch.items():
        iid = branch_issue_id(branch, prefix)
        if iid:
            issue_sessions.setdefault(iid, set()).add(sid)

    issue_durations: dict[str, list[int]] = {}
    for a in agents:
        if a.get("event_type") != "SubagentStop" or a.get("duration_ms") is None:
            continue
        sid = a.get("session_id")
        branch = session_branch.get(sid)
        iid = branch_issue_id(branch, prefix)
        if iid:
            issue_durations.setdefault(iid, []).append(a["duration_ms"])

    return (
        {k: sorted(v) for k, v in issue_sessions.items()},
        issue_durations,
        collector_live_since,
    )


def build_review_index() -> tuple[dict[str, int], datetime | None]:
    events_dir = instrumentation_dir(str(REPO_ROOT)) / "events"
    reviews = load_jsonl(events_dir / "reviews.jsonl")
    live_since = min((_parse_dt(r["ts"]) for r in reviews if r.get("ts")), default=None)
    max_iter: dict[str, int] = {}
    for r in reviews:
        iid = r.get("issue_id")
        if not iid:
            continue
        max_iter[iid] = max(max_iter.get(iid, 0), r.get("iteration_number", 0))
    return max_iter, live_since


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
def main() -> None:
    prefix = bd_prefix()
    nwo = repo_nwo()

    print(f"Fetching bd issues closed on/after {EPOCH_ZERO.date()}...", file=sys.stderr)
    issues = bd_closed_issues_since(EPOCH_ZERO)
    print(f"  {len(issues)} qualifying issues.", file=sys.stderr)

    print("Fetching merged PRs into develop (this can take a couple minutes)...", file=sys.stderr)
    develop_prs = list_merged_prs(nwo, "develop")
    for pr in develop_prs:
        pr["_commits"] = pr_commits(nwo, pr["number"])
    print(f"  {len(develop_prs)} merged PRs, {sum(len(p['_commits']) for p in develop_prs)} commits scanned.", file=sys.stderr)

    print("Indexing main's promotion (merge) commits...", file=sys.stderr)
    main_merges_raw = _run(
        ["git", "log", "origin/main", "--merges", "--first-parent", "--reverse", "--format=%H"]
    )
    main_merge_commits = [line for line in main_merges_raw.splitlines() if line.strip()]

    print("Indexing session/agent/review logs...", file=sys.stderr)
    issue_sessions, issue_durations, sessions_live_since = build_session_agent_index(prefix)
    review_iters, reviews_live_since = build_review_index()

    rows = []
    for issue in issues:
        issue_id = issue["id"]
        match = find_matching_pr(issue_id, develop_prs)

        pr_opened_at = merged_at = first_commit_at = None
        files_changed = lines_changed = None
        deployed_at = None

        if match:
            pr = match["pr"]
            first_commit_at = match["first_commit_at"]
            pr_opened_at = _parse_dt(pr["createdAt"])
            merged_at = _parse_dt(pr["mergedAt"])
            details = pr_details(nwo, pr["number"])
            if details:
                files_changed = details.get("changed_files")
                lines_changed = (details.get("additions") or 0) + (details.get("deletions") or 0)
            squash_sha = (pr.get("mergeCommit") or {}).get("oid")
            if squash_sha:
                deployed_at = find_deployed_at(nwo, squash_sha, main_merge_commits)

        sessions_for_issue = issue_sessions.get(issue_id)
        if sessions_for_issue is not None:
            session_count = len(sessions_for_issue)
            durations = issue_durations.get(issue_id, [])
            active_seconds = sum(durations) / 1000 if durations else (0 if session_count else None)
        elif sessions_live_since is not None and (merged_at or issue.get("closed_at")) and _parse_dt(issue.get("closed_at")) >= sessions_live_since:
            # Collector was live by the time this shipped, but no session on
            # a matching branch was ever recorded -- a genuine zero, not a gap.
            session_count = 0
            active_seconds = None
        else:
            # Either the collector didn't exist yet, or we can't tell -- not measured.
            session_count = None
            active_seconds = None

        closed_at = _parse_dt(issue.get("closed_at"))
        if issue_id in review_iters:
            reviewer_iterations = review_iters[issue_id]
        elif reviews_live_since is not None and closed_at is not None and closed_at >= reviews_live_since:
            reviewer_iterations = 0
        else:
            reviewer_iterations = None

        rows.append(
            {
                "issue_id": issue_id,
                "type": issue.get("issue_type"),
                "claimed_at": issue.get("started_at"),
                "first_commit_at": first_commit_at.isoformat() if first_commit_at else None,
                "pr_opened_at": pr_opened_at.isoformat() if pr_opened_at else None,
                "merged_at": merged_at.isoformat() if merged_at else None,
                "deployed_at": deployed_at.isoformat() if deployed_at else None,
                "active_seconds": active_seconds,
                "session_count": session_count,
                "reviewer_iterations": reviewer_iterations,
                "files_changed": files_changed,
                "lines_changed": lines_changed,
                # No stored raw event captures any of these three for any
                # issue in this project today -- see README "What this
                # cannot measure". Left null rather than guessed.
                "size_estimate_at_claim": None,  # bd's estimated_minutes column exists but is unused (0/281 issues have it set)
                "developer_model": None,
                "reviewer_model": None,
                "tooling_version": None,
                # No caused-by/discovered-from edge type exists in this bd
                # install (confirmed, see docs from the earlier bd-velocity
                # analysis and Phase 0 of this task) -- nothing to derive
                # "escaped to production" from.
                "escaped": None,
            }
        )

    write_csv(rows)
    write_sqlite(rows)
    print(f"\nWrote {len(rows)} rows to {OUT_DIR / 'shipped_issues.csv'} and shipped_issues.db", file=sys.stderr)


def write_csv(rows: list[dict]) -> None:
    path = OUT_DIR / "shipped_issues.csv"
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def write_sqlite(rows: list[dict]) -> None:
    path = OUT_DIR / "shipped_issues.db"
    if path.exists():
        path.unlink()
    conn = sqlite3.connect(path)
    if rows:
        cols = list(rows[0].keys())
        conn.execute(f"CREATE TABLE shipped_issues ({', '.join(c + ' TEXT' for c in cols)})")
        conn.executemany(
            f"INSERT INTO shipped_issues VALUES ({', '.join('?' for _ in cols)})",
            [[row[c] for c in cols] for row in rows],
        )
    else:
        conn.execute("CREATE TABLE shipped_issues (issue_id TEXT)")
    conn.commit()
    conn.close()


if __name__ == "__main__":
    main()
