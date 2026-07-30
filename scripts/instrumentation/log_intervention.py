#!/usr/bin/env python3
"""Append one record to .instrumentation/interventions.jsonl (committed --
unlike everything else under .instrumentation/, this file is meant to be
read by anyone looking at the repo's history, not just regenerated locally).

Usage:
  scripts/instrumentation/log_intervention.py \\
      --date 2026-07-26 \\
      --change "Adopted beads (bd) for issue tracking, replacing Linear" \\
      --expected-effect "Enables the whole shipped-issue join key (Bead trailers, claim timestamps); no prior process could have measured this at all" \\
      --segment claimed_at_to_first_commit_at

--expected-effect is required and must be non-empty: this log only has
value if the expected effect is recorded going in, not rationalized
afterward once the data comes back a certain way. There's no technical way
to enforce "before the change lands" from a script, but requiring the field
up front removes the easy way to skip it.

--segment should name one of the Phase 4 shipped_issues.csv segments this
change is expected to move (claimed_at_to_first_commit_at,
first_commit_at_to_pr_opened_at, pr_opened_at_to_merged_at,
merged_at_to_deployed_at, active_seconds, reviewer_iterations), or "other"
with the detail folded into --change / --expected-effect.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "hooks"))
from _common import SCHEMA_VERSION  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
INTERVENTIONS_PATH = REPO_ROOT / ".instrumentation" / "interventions.jsonl"

KNOWN_SEGMENTS = {
    "claimed_at_to_first_commit_at",
    "first_commit_at_to_pr_opened_at",
    "pr_opened_at_to_merged_at",
    "merged_at_to_deployed_at",
    "active_seconds",
    "reviewer_iterations",
    "other",
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--date", required=True, help="YYYY-MM-DD the change landed (or lands)")
    parser.add_argument("--change", required=True, help="what changed, one sentence")
    parser.add_argument("--expected-effect", required=True, help="what you expect to happen, filled in before the change lands")
    parser.add_argument("--segment", required=True, choices=sorted(KNOWN_SEGMENTS), help="which shipped-issue segment this should move")
    args = parser.parse_args()

    if not args.expected_effect.strip():
        parser.error("--expected-effect cannot be empty")

    record = {
        "schema_version": SCHEMA_VERSION,
        "date": args.date,
        "change_description": args.change,
        "expected_effect": args.expected_effect,
        "segment_expected_to_move": args.segment,
    }

    INTERVENTIONS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(INTERVENTIONS_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, sort_keys=True) + "\n")

    print(f"Logged intervention: {args.date} — {args.change}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
