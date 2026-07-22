# Dependency Audit

Pre-launch dependency vulnerability audit (technical-design §9). This is a living
record — update it when a fresh audit is run or advisories change.

## Method

- **Backend:** `pip-audit` against the resolved virtualenv (`pip freeze`, minus the
  local editable package), and wired into CI as `pip-audit --skip-editable`.
- **Frontend:** `npm audit` — triaged prod (`--omit=dev`) separately from dev tooling.
- Non-blocking audit steps run on every PR in `.github/workflows/ci.yml` so a
  newly-vulnerable dependency surfaces without silently regressing.

## 2026-06-15 (MYS-47)

### Backend — clean
`pip-audit` reported **no known vulnerabilities**.

### Frontend — prod clean after fix; dev tooling deferred

Initial audit: 8 advisories (1 critical, 3 high, 4 moderate).

**Remediated (non-breaking `npm audit fix`):**

| Package | Sev | Advisory | Resolution |
|---|---|---|---|
| `react-router` / `react-router-dom` | moderate | GHSA-2j2x-hqr9-3h42 — open redirect via protocol-relative `//` URL | bumped 6.30.3 → 6.30.4 (within `^6`) |
| `form-data` (transitive) | high | GHSA-hmw2-7cc7-3qxx — CRLF injection | resolved by `npm audit fix` |

After the fix, **`npm audit --omit=dev` reports 0 vulnerabilities** — the shipped
runtime bundle is clean. Typecheck + full frontend test suite pass on the bump.

**Deferred — dev-only tooling (not in the shipped bundle):**

| Package | Sev | Notes |
|---|---|---|
| `vitest` | critical | Vitest UI server arbitrary file read — only when the UI server is run; not used in CI/prod |
| `vite` | high | dev-server path traversal in optimized deps |
| `esbuild` | high | dev-server request issue |
| `@vitest/mocker`, `vite-node` | moderate | vitest ecosystem |

These are exploitable only against a running local dev server, never in the
production build. Fixing them requires breaking major bumps (`vite` 6→7,
`vitest` 3→x) and so is **out of scope for the hardening pass** — tracked
separately for a deliberate tooling upgrade rather than forced here.
