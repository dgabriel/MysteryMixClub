#!/usr/bin/env python3
"""
ONE-TIME backfill: reconstruct historical Claude Code token/cost usage for the
MMC agent workflow from local session transcripts, for MysteryMixClub-ysu2.

This is explicitly NOT a standing pipeline. The `~/.claude/projects/*/*.jsonl`
transcript format is Claude Code's internal format and is not a supported,
versioned API -- it can and does change between releases. Run this script by
hand, once (or occasionally, bounded by --before, to top up before live
telemetry took over), review the output, load it, done. Do not cron it.

What it does:
  1. Walks this repo's Claude Code project transcript directory:
       ~/.claude/projects/<mangled-repo-path>/
     - top-level *.jsonl files  -> the "main" (orchestrator) session
     - */subagents/*.jsonl      -> individual subagent invocations, with a
       companion *.meta.json carrying the subagent's declared type
  2. For each assistant message with usage data, dedupes by Anthropic message
     id (a single API response is persisted as one transcript line per
     content block -- thinking/tool_use/text -- all sharing one usage blob;
     counting every line would multiply token counts by the number of content
     blocks).
  3. Normalizes each invocation to one of MMC's known subagent roles
     (developer/tester/reviewer/ui-agent/uiux-designer/devops/product-manager)
     or a small set of Claude Code built-in buckets (main/explore/plan/
     general-purpose/other), using the subagent's .meta.json when available
     and a conservative name-substring heuristic otherwise.
  4. Buckets events into daily counters (default) and writes:
       output/usage_events_raw.jsonl   -- full per-request audit trail
       output/claude_code_backfill.om  -- OpenMetrics file, ready for
                                          `promtool tsdb create-blocks-from
                                          openmetrics`, every series tagged
                                          source="backfill" (never "live").

Cost is a best-effort estimate from a small hardcoded per-model-family price
table (see PRICING_USD_PER_MTOK below) -- it will drift out of date. Per the
ticket's own note: treat `/cost` and provider billing as ground truth for
cost; this is directionally useful for relative agent/model comparison only.

Usage:
    python3 extract_usage.py [--claude-dir ~/.claude/projects] \\
        [--repo-path /Users/dgabriel/claudeProjects/MysteryMixClub] \\
        [--bucket 1d] [--before 2026-07-26T00:00:00Z] [--dry-run] \\
        [--out-dir ./output]

See ../README.md for how to load the resulting .om file into Prometheus.
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys
from collections import defaultdict
from datetime import datetime, timezone, date
from typing import Any, Iterable

TOKEN_TYPES = ("input", "output", "cacheRead", "cacheCreation")

# Best-effort, approximate, will go stale. Treat live claude_code.cost.usage
# and provider billing as ground truth (matches the ticket's own note).
# USD per million tokens: (input, output). Cache write assumed at 1.25x input
# (5-minute ephemeral default); cache read assumed at 0.1x input -- both are
# Anthropic's standard cache pricing ratios, not model-specific figures.
PRICING_USD_PER_MTOK = {
    "opus": (15.00, 75.00),
    "sonnet": (3.00, 15.00),
    "haiku": (0.80, 4.00),
}


def normalize_agent_name(
    custom_agent_type: str | None, agent_type: str | None
) -> tuple[str, str]:
    """Return (bucketed_name, raw_name) for Prometheus-label-safe attribution.

    Raw invocation names (e.g. "mys201-review4b") are NOT used as label
    values -- they'd blow up cardinality for no analytical benefit. They're
    preserved in the raw audit JSONL instead.
    """
    raw = custom_agent_type or agent_type or "unknown"
    if custom_agent_type:
        return custom_agent_type, raw
    if agent_type is None:
        return "unknown", raw

    at = agent_type.strip()
    at_lower = at.lower()

    # Claude Code built-in agent types -- keep distinct from MMC's 5 named
    # subagents so they don't get miscounted as one of the 5.
    if at in ("Explore", "Plan", "general-purpose"):
        return at_lower, raw

    known = {
        "developer",
        "tester",
        "reviewer",
        "ui-agent",
        "devops",
        "uiux-designer",
        "product-manager",
    }
    if at_lower in known:
        return at_lower, raw

    # Heuristic bucketing for older/task-specific invocation names
    # (e.g. "review-mys105", "mys201-dev4", "design-mys120").
    # Order matters: check the more specific buckets before generic ones.
    if "devops" in at_lower or "infra" in at_lower:
        return "devops", raw
    if "review" in at_lower:
        return "reviewer", raw
    if "test" in at_lower:
        return "tester", raw
    if "design" in at_lower or "uiux" in at_lower:
        return "uiux-designer", raw
    if re.search(r"\bpm\b", at_lower) or "product" in at_lower:
        return "product-manager", raw
    if "ui" in at_lower:
        return "ui-agent", raw
    if "plan" in at_lower:
        return "plan", raw
    if "explore" in at_lower:
        return "explore", raw
    if "dev" in at_lower:
        return "developer", raw
    return "other", raw


def price_for_model(model: str | None) -> tuple[float, float] | None:
    if not model:
        return None
    m = model.lower()
    for family, prices in PRICING_USD_PER_MTOK.items():
        if family in m:
            return prices
    return None


def estimate_cost_usd(
    model: str | None,
    input_tok: int,
    output_tok: int,
    cache_read_tok: int,
    cache_creation_tok: int,
) -> float | None:
    prices = price_for_model(model)
    if prices is None:
        return None
    input_price, output_price = prices
    cache_write_price = input_price * 1.25
    cache_read_price = input_price * 0.10
    total = (
        input_tok * input_price
        + output_tok * output_price
        + cache_creation_tok * cache_write_price
        + cache_read_tok * cache_read_price
    ) / 1_000_000
    return total


def mangle_repo_path(repo_path: str) -> str:
    """Reproduce Claude Code's ~/.claude/projects/<name> directory naming:
    absolute path with '/' replaced by '-'. Verified against this machine's
    actual ~/.claude/projects/-Users-dgabriel-claudeProjects-MysteryMixClub."""
    abs_path = os.path.abspath(repo_path)
    return abs_path.replace("/", "-")


def parse_iso(ts: str) -> datetime:
    ts = ts.replace("Z", "+00:00")
    return datetime.fromisoformat(ts)


def iter_jsonl(path: str) -> Iterable[dict[str, Any]]:
    with open(path, "r", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def sum_usage_fields(usage: dict[str, Any]) -> tuple[int, int, int, int]:
    """Prefer the `iterations` breakdown when present (some transcript lines
    carry an all-zero top-level usage with the real numbers only in
    `iterations`); fall back to the top-level fields otherwise."""
    iterations = usage.get("iterations")
    if iterations:
        inp = sum(it.get("input_tokens", 0) for it in iterations)
        out = sum(it.get("output_tokens", 0) for it in iterations)
        cread = sum(it.get("cache_read_input_tokens", 0) for it in iterations)
        ccreate = sum(it.get("cache_creation_input_tokens", 0) for it in iterations)
        return inp, out, cread, ccreate
    return (
        usage.get("input_tokens", 0),
        usage.get("output_tokens", 0),
        usage.get("cache_read_input_tokens", 0),
        usage.get("cache_creation_input_tokens", 0),
    )


def load_meta(meta_path: str) -> dict[str, Any]:
    try:
        with open(meta_path) as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError):
        return {}


def extract(project_dir: str, before: datetime | None) -> dict[str, Any]:
    seen_message_ids: set[str] = set()
    token_events: list[dict[str, Any]] = []
    session_first_seen: dict[str, datetime] = {}
    pr_first_seen: dict[tuple[str, int], datetime] = {}
    parse_errors = 0

    # 1. Main session files (top-level *.jsonl directly in the project dir).
    main_files = sorted(glob.glob(os.path.join(project_dir, "*.jsonl")))
    for path in main_files:
        session_id = os.path.splitext(os.path.basename(path))[0]
        for obj in iter_jsonl(path):
            try:
                ts_raw = obj.get("timestamp")
                if ts_raw:
                    ts = parse_iso(ts_raw)
                    if before is not None and ts >= before:
                        continue
                    session_first_seen.setdefault(session_id, ts)
                    session_first_seen[session_id] = min(
                        session_first_seen[session_id], ts
                    )

                if obj.get("type") == "assistant":
                    msg = obj.get("message", {})
                    usage = msg.get("usage")
                    msg_id = msg.get("id")
                    if not usage or not msg_id or msg_id in seen_message_ids:
                        continue
                    seen_message_ids.add(msg_id)
                    if not ts_raw:
                        continue
                    inp, out, cread, ccreate = sum_usage_fields(usage)
                    token_events.append(
                        {
                            "ts": ts,
                            "session_id": session_id,
                            "agent_name": "main",
                            "agent_name_raw": "main",
                            "model": msg.get("model"),
                            "input": inp,
                            "output": out,
                            "cacheRead": cread,
                            "cacheCreation": ccreate,
                        }
                    )
                elif obj.get("type") == "pr-link":
                    pr_num = obj.get("prNumber")
                    if pr_num is not None and ts_raw:
                        key = (session_id, pr_num)
                        pr_first_seen.setdefault(key, ts)
                        pr_first_seen[key] = min(pr_first_seen[key], ts)
            except Exception:
                parse_errors += 1
                continue

    # 2. Subagent files: <session-uuid>/subagents/agent-*.jsonl (+ .meta.json)
    subagent_files = sorted(
        glob.glob(os.path.join(project_dir, "*", "subagents", "agent-*.jsonl"))
    )
    for path in subagent_files:
        session_id = os.path.basename(os.path.dirname(os.path.dirname(path)))
        meta_path = path[: -len(".jsonl")] + ".meta.json"
        meta = load_meta(meta_path)
        agent_name, agent_name_raw = normalize_agent_name(
            meta.get("customAgentType"), meta.get("agentType")
        )
        for obj in iter_jsonl(path):
            try:
                if obj.get("type") != "assistant":
                    continue
                msg = obj.get("message", {})
                usage = msg.get("usage")
                msg_id = msg.get("id")
                if not usage or not msg_id or msg_id in seen_message_ids:
                    continue
                seen_message_ids.add(msg_id)
                ts_raw = obj.get("timestamp")
                if not ts_raw:
                    continue
                ts = parse_iso(ts_raw)
                if before is not None and ts >= before:
                    continue
                inp, out, cread, ccreate = sum_usage_fields(usage)
                token_events.append(
                    {
                        "ts": ts,
                        "session_id": session_id,
                        "agent_name": agent_name,
                        "agent_name_raw": agent_name_raw,
                        "model": msg.get("model"),
                        "input": inp,
                        "output": out,
                        "cacheRead": cread,
                        "cacheCreation": ccreate,
                    }
                )
            except Exception:
                parse_errors += 1
                continue

    return {
        "token_events": token_events,
        "session_first_seen": session_first_seen,
        "pr_first_seen": pr_first_seen,
        "parse_errors": parse_errors,
        "main_files": len(main_files),
        "subagent_files": len(subagent_files),
    }


def bucket_day(ts: datetime) -> date:
    return ts.astimezone(timezone.utc).date()


def build_daily_aggregates(extracted: dict[str, Any]) -> dict[str, Any]:
    token_by_day: dict[tuple[date, str, str, str], int] = defaultdict(
        int
    )  # (day, model, type, agent) -> tokens
    cost_by_day: dict[tuple[date, str, str], float] = defaultdict(
        float
    )  # (day, model, agent) -> usd
    cost_unpriced_models: set[str] = set()

    for ev in extracted["token_events"]:
        day = bucket_day(ev["ts"])
        model = ev["model"] or "unknown"
        agent = ev["agent_name"]
        for ttype, count in (
            ("input", ev["input"]),
            ("output", ev["output"]),
            ("cacheRead", ev["cacheRead"]),
            ("cacheCreation", ev["cacheCreation"]),
        ):
            if count:
                token_by_day[(day, model, ttype, agent)] += count
        cost = estimate_cost_usd(
            model, ev["input"], ev["output"], ev["cacheRead"], ev["cacheCreation"]
        )
        if cost is None:
            cost_unpriced_models.add(model)
        else:
            cost_by_day[(day, model, agent)] += cost

    session_by_day: dict[date, int] = defaultdict(int)
    for _sid, ts in extracted["session_first_seen"].items():
        session_by_day[bucket_day(ts)] += 1

    pr_by_day: dict[date, int] = defaultdict(int)
    for _key, ts in extracted["pr_first_seen"].items():
        pr_by_day[bucket_day(ts)] += 1

    return {
        "token_by_day": token_by_day,
        "cost_by_day": cost_by_day,
        "cost_unpriced_models": cost_unpriced_models,
        "session_by_day": session_by_day,
        "pr_by_day": pr_by_day,
    }


def to_cumulative(daily: dict[tuple, float]) -> dict[tuple, list[tuple[date, float]]]:
    """Group a {(day, *labels): value} dict by its label tuple (excluding day)
    and convert each label-tuple's daily deltas into a running cumulative
    total ordered by day -- required because Prometheus counters (and
    promtool's OpenMetrics backfill) are consumed with rate()/increase(),
    which expect a monotonically non-decreasing series, not discrete deltas.
    """
    series: dict[tuple, list[tuple[date, float]]] = defaultdict(list)
    for key, value in daily.items():
        day = key[0]
        labels = key[1:]
        series[labels].append((day, value))
    cumulative: dict[tuple, list[tuple[date, float]]] = {}
    for labels, points in series.items():
        points.sort(key=lambda p: p[0])
        running = 0.0
        out = []
        for day, delta in points:
            running += delta
            out.append((day, running))
        cumulative[labels] = out
    return cumulative


def day_to_epoch_seconds(d: date) -> int:
    # Start-of-day (00:00 UTC), NOT end-of-day. Prometheus's TSDB head only
    # accepts samples with strictly increasing timestamps; if the backfill
    # includes "today" and buckets it at 23:59, the block for today lands in
    # the future relative to right-now, and every subsequent *live* scrape
    # earlier in the day gets rejected as "too old" ("out of bounds") until
    # wall-clock time catches up. Start-of-day sidesteps this: it's always
    # <= any real event timestamp seen that day, and always in the past
    # relative to "now" for any day up to and including today.
    return int(
        datetime(d.year, d.month, d.day, 0, 0, 0, tzinfo=timezone.utc).timestamp()
    )


def write_openmetrics(aggregates: dict[str, Any], out_path: str) -> int:
    lines: list[str] = []
    sample_count = 0

    def emit(
        metric: str,
        label_names: list[str],
        cumulative: dict[tuple, list[tuple[date, float]]],
    ):
        nonlocal sample_count
        lines.append(f"# TYPE {metric} counter")
        for labels, points in cumulative.items():
            label_str_parts = [
                f'{name}="{value}"' for name, value in zip(label_names, labels)
            ]
            label_str_parts.append('source="backfill"')
            label_str = ",".join(label_str_parts)
            for day, value in points:
                ts = day_to_epoch_seconds(day)
                lines.append(f"{metric}{{{label_str}}} {value} {ts}")
                sample_count += 1

    token_cum = to_cumulative(aggregates["token_by_day"])
    emit("claude_code_token_usage_total", ["model", "type", "agent_name"], token_cum)

    cost_cum = to_cumulative(aggregates["cost_by_day"])
    emit("claude_code_cost_usage_total", ["model", "agent_name"], cost_cum)

    session_cum = to_cumulative(
        {(day,): count for day, count in aggregates["session_by_day"].items()}
    )
    emit("claude_code_session_count_total", [], session_cum)

    pr_cum = to_cumulative(
        {(day,): count for day, count in aggregates["pr_by_day"].items()}
    )
    emit("claude_code_pull_request_count_total", [], pr_cum)

    lines.append("# EOF")
    with open(out_path, "w") as fh:
        fh.write("\n".join(lines) + "\n")
    return sample_count


def write_raw_audit(extracted: dict[str, Any], out_path: str) -> None:
    with open(out_path, "w") as fh:
        for ev in extracted["token_events"]:
            row = dict(ev)
            row["ts"] = ev["ts"].isoformat()
            row["source"] = "backfill"
            fh.write(json.dumps(row) + "\n")


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--claude-dir", default=os.path.expanduser("~/.claude/projects"))
    ap.add_argument(
        "--repo-path",
        default="/Users/dgabriel/claudeProjects/MysteryMixClub",
        help="Repo path whose Claude Code transcripts should be backfilled (mangled to find the ~/.claude/projects subdir).",
    )
    ap.add_argument(
        "--before",
        default=None,
        help="ISO8601 UTC cutoff (e.g. 2026-07-26T00:00:00Z). Only backfill events strictly before this. "
        "Defaults to the start of today (UTC) -- i.e. 'yesterday and earlier' -- both to match the ticket's "
        "'pre-instrumentation period' framing and, more importantly, because Prometheus's TSDB head rejects "
        "any live-scraped sample that is chronologically older than a block already ingested; backfilling "
        "today's own data risks the block for 'today' landing ahead of live scrapes still to come today. "
        "On re-runs after live telemetry is on, pass the exact moment CLAUDE_CODE_ENABLE_TELEMETRY was set "
        "to top up any remaining gap without overlapping live data.",
    )
    ap.add_argument(
        "--out-dir",
        default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "output"),
    )
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="Print summary stats only; do not write output files.",
    )
    args = ap.parse_args()

    project_dir_name = mangle_repo_path(args.repo_path)
    project_dir = os.path.join(args.claude_dir, project_dir_name)
    if not os.path.isdir(project_dir):
        print(
            f"ERROR: no Claude Code project directory found at {project_dir}",
            file=sys.stderr,
        )
        return 1

    if args.before:
        before = parse_iso(args.before)
    else:
        today = datetime.now(timezone.utc).date()
        before = datetime(today.year, today.month, today.day, tzinfo=timezone.utc)

    extracted = extract(project_dir, before)
    aggregates = build_daily_aggregates(extracted)

    total_tokens = sum(aggregates["token_by_day"].values())
    total_sessions = len(extracted["session_first_seen"])
    total_prs = len(extracted["pr_first_seen"])
    dates = sorted(set(k[0] for k in aggregates["token_by_day"].keys()))

    print(f"Project dir:         {project_dir}")
    print(f"Main session files:  {extracted['main_files']}")
    print(f"Subagent files:      {extracted['subagent_files']}")
    print(f"Parse errors:        {extracted['parse_errors']} (skipped, non-fatal)")
    print(f"Unique API messages: {len(extracted['token_events'])}")
    print(f"Distinct sessions:   {total_sessions}")
    print(f"Distinct PRs seen:   {total_prs}")
    print(f"Total tokens:        {total_tokens:,.0f}")
    if dates:
        print(f"Date range covered:  {dates[0]} .. {dates[-1]}")
    if aggregates["cost_unpriced_models"]:
        print(
            f"WARNING: no price table entry for model(s), cost omitted for: {sorted(aggregates['cost_unpriced_models'])}"
        )

    if args.dry_run:
        print("\n--dry-run set: no output files written.")
        return 0

    os.makedirs(args.out_dir, exist_ok=True)
    raw_path = os.path.join(args.out_dir, "usage_events_raw.jsonl")
    om_path = os.path.join(args.out_dir, "claude_code_backfill.om")
    write_raw_audit(extracted, raw_path)
    n_samples = write_openmetrics(aggregates, om_path)

    print(f"\nWrote {len(extracted['token_events'])} raw events to {raw_path}")
    print(f"Wrote {n_samples} OpenMetrics samples to {om_path}")
    print(
        "Next: run ./load_backfill.sh to turn this into Prometheus TSDB blocks. See ../README.md."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
