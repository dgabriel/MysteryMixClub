#!/usr/bin/env python3
"""Multi-language linter adapter for Flaught's tools.linter (ADR 0031).

Flaught's tools.linter.command is a single shell command, and its JSON parser
(parseLinterJsonOutput in @flaught/core) only actually recognizes ESLint's own
nested shape -- [{filePath, messages: [...]}]. Its "Ruff format" branch for a
flat violation array is unreachable dead code in @flaught/core 0.13.0: both
shapes satisfy the same `Array.isArray(data)` check, so the ESLint branch
always runs first, finds no `.messages` on a flat-shaped entry, and silently
returns zero findings. This project already sidestepped that trap for Python
(see the comment above `tools.linter` in .advreview.yml): ruff/mypy run
outside Flaught, in real CI + hooks, rather than fight it.

For Swift, this script sidesteps the same trap for a stack that DOES belong in
Flaught's automated review: run each configured linter, normalize its native
output into ESLint's own shape, and merge everything into one array Flaught's
parser already understands correctly. .advreview.yml points
tools.linter.command at this script instead of a bare linter invocation.

Add a language by adding one function to LINTERS below -- nothing else in
this file, .advreview.yml, or the CI workflow needs to change shape, though a
genuinely new toolchain still needs its own CI install step.

A linter that isn't installed is skipped, not fatal -- the same "degrade
gracefully" contract Flaught's own tool runner uses. This script always exits
0 and always prints a valid JSON array (empty at worst): a linter exiting
non-zero because it found real issues is not a wrapper failure -- Flaught's
own execCommandShell already tolerates that from a tool it invokes directly --
and there's no reason to make this script's exit code carry two meanings.
"""

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _run(cmd: list[str], cwd: Path) -> str | None:
    """Run cmd, returning stdout whether it exited 0 or not -- both ESLint and
    SwiftLint exit non-zero when they find real issues, which is not the same
    thing as the tool failing to run. Returns None only when the tool itself
    couldn't be found, invoked, or finished in time."""
    try:
        proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=180)
    except FileNotFoundError:
        sys.stderr.write(f"flaught_linter: {cmd[0]} not installed, skipping\n")
        return None
    except subprocess.TimeoutExpired:
        sys.stderr.write(f"flaught_linter: {cmd[0]} timed out, skipping\n")
        return None
    return proc.stdout


def run_eslint() -> list[dict]:
    """ESLint already emits [{filePath, messages: [...]}] -- pass it through
    unchanged; it's the one shape Flaught's parser was actually written for."""
    stdout = _run(["npx", "eslint", "--format", "json", "."], cwd=REPO_ROOT / "frontend")
    if not stdout:
        return []
    try:
        return json.loads(stdout)
    except json.JSONDecodeError:
        sys.stderr.write("flaught_linter: eslint output was not valid JSON, skipping\n")
        return []


def run_swiftlint() -> list[dict]:
    """SwiftLint's --reporter json is a FLAT array -- [{file, line, reason,
    rule_id, severity, ...}] -- with no per-file nesting at all. Group it back
    into ESLint's per-file shape by hand."""
    target = REPO_ROOT / "frontend" / "ios" / "App" / "App"
    stdout = _run(["swiftlint", "lint", "--reporter", "json", "--quiet", str(target)], cwd=REPO_ROOT)
    if not stdout:
        return []
    try:
        violations = json.loads(stdout) if stdout.strip() else []
    except json.JSONDecodeError:
        sys.stderr.write("flaught_linter: swiftlint output was not valid JSON, skipping\n")
        return []

    by_file: dict[str, list[dict]] = {}
    for v in violations:
        by_file.setdefault(v.get("file", ""), []).append(
            {
                "message": v.get("reason", "SwiftLint issue"),
                # ESLint severity is the int Flaught's own mapEslintSeverity()
                # reads directly: 2 -> high (its "error"), 1 -> low (its
                # "warning") -- not SwiftLint's own "Error"/"Warning" strings.
                "severity": 2 if v.get("severity") == "Error" else 1,
                "line": v.get("line", 0),
                "ruleId": v.get("rule_id", "unknown"),
                "source": v.get("reason", ""),
            }
        )
    return [{"filePath": f, "messages": msgs} for f, msgs in by_file.items()]


# Add a language here -- each entry just needs to return Flaught's
# [{filePath, messages: [...]}] shape, however its own native tool spells it.
LINTERS = [run_eslint, run_swiftlint]


def main() -> int:
    combined: list[dict] = []
    for linter in LINTERS:
        try:
            combined.extend(linter())
        except Exception as exc:  # noqa: BLE001 -- one linter's bug must not blank the others
            sys.stderr.write(f"flaught_linter: {linter.__name__} raised {exc!r}, skipping\n")
    print(json.dumps(combined))
    return 0


if __name__ == "__main__":
    sys.exit(main())
