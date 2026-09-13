# ADR 0031: Cover Swift in Flaught's linter tool through a shape-normalizing adapter script

**Status:** Accepted
**Date:** 2026-09-13

## Context

The iOS proof (MysteryMixClub-yyuq, ADR 0028/0029) added real Swift source —
`MusicPlugin.swift`, `SceneDelegate.swift`, and the rest of the Capacitor
scaffold. Flaught's adversarial review (`.advreview.yml`) has no static-lint
coverage of it: `tools.linter.command` runs bare ESLint, scoped to `frontend/`.

ADR 0025 already documented why a second language can't just be appended:
`tools.linter.command` is a single shell command, and a naive `eslint ...;
ruff ...` chain doesn't produce one parseable JSON array. That ADR's answer for
Python was to leave it uncovered by Flaught's linter tool entirely — ruff and
mypy already run for real elsewhere (CI's backend job, pre-commit, pre-push).

Reading `@flaught/core`'s own source (`dist/tools/runner.js`,
`parseLinterJsonOutput`) while scoping this found something ADR 0025 didn't
have available at the time: the "concatenation" framing understated the real
constraint. Flaught's JSON parser doesn't inspect a tool's *identity* — it
inspects *shape*, and it only actually understands one shape:
`[{filePath, messages: [...]}]`, ESLint's own nested format. A second branch
in the same function, commented "Ruff format," is meant to handle a flat
violation array — but it is dead code: both shapes satisfy the same
`Array.isArray(data)` guard, so the ESLint branch always runs first, finds no
`.messages` property on a flat-shaped entry, and silently returns zero
findings. Verified directly: running `swiftlint lint --reporter json` (a flat
array — `[{file, line, reason, rule_id, severity}]`, structurally identical in
shape to Ruff's) through Flaught's parser produces zero findings against
`MusicPlugin.swift`, even though the same file has three real, defensible
SwiftLint findings (`cyclomatic_complexity`, `file_length`,
`type_body_length`) confirmed by running SwiftLint directly. This is likely
also why Python's ruff was never routed through `tools.linter` — the same trap
would have silently produced a clean scan that wasn't one.

## Decision

Point `tools.linter.command` at `scripts/instrumentation/flaught_linter.py`
instead of a bare tool invocation. It runs each configured linter, normalizes
every one's *native* output into the one shape Flaught's parser actually
handles correctly, and merges the results into a single valid array —
sidestepping the shape bug rather than working around it per-tool. ESLint's
own output already matches and passes through unchanged; SwiftLint's flat
array is grouped back into per-file `messages` by hand, with its
`"Error"`/`"Warning"` strings mapped onto the same integer severities (`2`/`1`)
`mapEslintSeverity()` already expects.

This is deliberately extensible: adding a language means adding one function
to `LINTERS` in that script — nothing in `.advreview.yml` or this ADR's
reasoning needs to change shape for the next one, though a genuinely new
toolchain still needs its own CI install step, as SwiftLint does below. A
linter that isn't installed is skipped, not fatal, matching Flaught's own
stated "degrade gracefully" design principle for its tools.

`.swiftlint.yml` (repo root) excludes `frontend/ios/App/CapApp-SPM` (Capacitor-
CLI-managed, its own header says not to touch it) and raises `line_length` to
160/250 — verified against this repo's actual files, not guessed: the stock
120/200 default was flagging Apple's/Capacitor's own generated comments in
`AppDelegate.swift` (up to 285 characters) as the entire source of noise,
while `MusicPlugin.swift`'s three real findings sit in a different rule family
untouched by that change.

CI installs SwiftLint's official Linux release
(`swiftlint_linux_amd64.zip`'s `swiftlint-static` asset) rather than a full
Swift toolchain — it's statically linked specifically so a bare `ubuntu-latest`
runner needs nothing else, and the version is pinned exactly, matching
Flaught's own pin (ADR 0017).

## Consequences

Flaught's LLM review pass was never blind to Swift — it reads the full diff
regardless of `tools.linter`'s scope — but it now also gets real deterministic
grounding for Swift findings, the same evidentiary backing ESLint gives the JS
diff, rather than relying on the LLM's read alone.

This is now the second tool-shape workaround this project carries for
`@flaught/core` 0.13.0 (the first being the linter auto-detection fix in ADR
0025 itself). Neither is filed upstream as of this writing. If `@flaught/core`
fixes the dead "Ruff format" branch in a future release, this adapter's
per-tool normalization becomes redundant for any linter whose native output
happens to already match Flaught's now-working generic path — but the
extensibility pattern (one script, one shape, one place to add a language)
remains the right structure regardless, so there's no reason to unwind it
reactively.

## Revisit if

`@flaught/core` ships a real multi-linter or plugin mechanism natively, or the
dead "Ruff format" branch gets fixed upstream — either would make maintaining
this adapter no longer the smallest correct option.

## References

- [ADR 0025](0025-flaught-linter-eslint-only.md)
- [ADR 0028](0028-prototype-ios-with-capacitor-and-native-musickit.md)
- `scripts/instrumentation/flaught_linter.py`
- `@flaught/core` 0.13.0, `dist/tools/runner.js` — `parseLinterJsonOutput`
- https://github.com/realm/SwiftLint/releases
